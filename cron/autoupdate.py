import logging
from typing import List, Tuple
from django.utils import timezone
from cjworkbench.pg_render_locker import PgRenderLocker, WorkflowAlreadyLocked
from cjworkbench.sync import database_sync_to_async
from server import rabbitmq, websockets
from cjwstate.models import WfModule


logger = logging.getLogger(__name__)


@database_sync_to_async
def load_pending_wf_modules() -> List[Tuple[int, WfModule]]:
    """Return list of (workflow_id, wf_module) with pending fetches."""
    now = timezone.now()
    # WfModule.workflow_id is a database operation
    return [
        (wfm.workflow_id, wfm)
        for wfm in WfModule.objects.filter(
            is_deleted=False,
            tab__is_deleted=False,
            is_busy=False,  # not already scheduled
            auto_update_data=True,  # user wants auto-update
            next_update__isnull=False,  # DB isn't inconsistent
            next_update__lte=now,  # enough time has passed
        )
    ]


@database_sync_to_async
def set_wf_module_busy(wf_module):
    # Database writes can't be on the event-loop thread
    wf_module.is_busy = True
    wf_module.save(update_fields=["is_busy"])


async def queue_fetches(pg_render_locker: PgRenderLocker):
    """
    Queue all pending fetches in RabbitMQ.

    We'll set is_busy=True as we queue them, so we don't send double-fetches.
    """
    wf_modules = await load_pending_wf_modules()

    for workflow_id, wf_module in wf_modules:
        # Don't schedule a fetch if we're currently rendering.
        #
        # This still lets us schedule a fetch if a render is _queued_, so it
        # doesn't solve any races. But it should lower the number of fetches of
        # resource-intensive workflows.
        #
        # Using pg_render_locker means we can only queue a fetch _between_
        # renders. The fetch/render queues may be non-empty (we aren't
        # checking); but we're giving the renderers a chance to tackle some
        # backlog.
        try:
            async with pg_render_locker.render_lock(workflow_id) as lock:
                # At this moment, the workflow isn't rendering. Let's pass
                # through and queue the fetch.
                await lock.stall_others()  # required by the PgRenderLocker API

            logger.info("Queue fetch of wf_module(%d, %d)", workflow_id, wf_module.id)
            await set_wf_module_busy(wf_module)
            await websockets.ws_client_send_delta_async(
                workflow_id,
                {
                    "updateWfModules": {
                        str(wf_module.id): {"is_busy": True, "fetch_error": ""}
                    }
                },
            )
            await rabbitmq.queue_fetch(wf_module)
        except WorkflowAlreadyLocked:
            # Don't queue a fetch. We'll revisit this WfModule next time we
            # query for pending fetches.
            pass
