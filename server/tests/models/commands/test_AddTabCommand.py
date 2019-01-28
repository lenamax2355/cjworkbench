import asyncio
from unittest.mock import patch
from server.models import Workflow
from server.models.commands import AddTabCommand
from server.tests.utils import DbTestCase


async def async_noop(*args, **kwargs):
    pass


class AddTabCommandTest(DbTestCase):
    @patch('server.websockets.ws_client_send_delta_async', async_noop)
    def test_append_tab(self):
        workflow = Workflow.create_and_init(selected_tab_position=0)
        tab1 = workflow.tabs.first()

        cmd = self.run_with_async_db(AddTabCommand.create(workflow=workflow,
                                                          slug='tab-1',
                                                          name='A'))
        new_tab = workflow.live_tabs.get(position=1)
        self.assertEqual(new_tab.name, 'A')
        self.assertEqual(new_tab.slug, 'tab-1')
        self.assertEqual(
            list(workflow.live_tabs.values_list('id', 'position')),
            [(tab1.id, 0), (new_tab.id, 1)]
        )

        self.run_with_async_db(cmd.backward())
        self.assertEqual(
            list(workflow.live_tabs.values_list('id', 'position')),
            [(tab1.id, 0)]
        )

    @patch('server.websockets.ws_client_send_delta_async', async_noop)
    def test_no_hard_or_soft_delete_when_deleting_applied_delta(self):
        workflow = Workflow.create_and_init()
        cmd = self.run_with_async_db(AddTabCommand.create(workflow=workflow,
                                                          slug='tab-1',
                                                          name='A'))
        cmd.delete()
        self.assertEquals(workflow.live_tabs.count(), 2)

    @patch('server.websockets.ws_client_send_delta_async')
    def test_ws_data(self, send_delta):
        future_none = asyncio.Future()
        future_none.set_result(None)
        send_delta.return_value = future_none

        workflow = Workflow.create_and_init(selected_tab_position=0)
        tab1 = workflow.tabs.first()
        cmd = self.run_with_async_db(AddTabCommand.create(workflow=workflow,
                                                          slug='tab-1',
                                                          name='A'))
        new_tab = workflow.live_tabs.get(position=1)
        delta1 = send_delta.call_args[0][1]
        self.assertEqual(delta1['updateWorkflow']['tab_ids'],
                         [tab1.id, new_tab.id])
        self.assertEqual(list(delta1['updateTabs'].keys()), [str(new_tab.id)])
        with self.assertRaises(KeyError):
            delta1['clearTabIds']

        self.run_with_async_db(cmd.backward())
        delta2 = send_delta.call_args[0][1]
        self.assertEqual(delta2['updateWorkflow']['tab_ids'], [tab1.id])
        with self.assertRaises(KeyError):
            delta2['updateTabs']
        self.assertEqual(delta2['clearTabIds'], [new_tab.id])
