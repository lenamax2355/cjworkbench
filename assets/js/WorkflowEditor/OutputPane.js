import React from 'react'
import PropTypes from 'prop-types'
import propTypes from '../propTypes'
import { connect } from 'react-redux'
import { Trans } from '@lingui/macro'
import DelayedTableSwitcher from '../table/DelayedTableSwitcher'
import OutputIframe from '../OutputIframe'
import selectIsReadOnly from '../selectors/selectIsReadOnly'
import selectWorkflowIdOrSecretId from '../selectors/selectWorkflowIdOrSecretId'

/**
 * Output of currently-selected module.
 */
export class OutputPane extends React.Component {
  static propTypes = {
    loadRows: PropTypes.func.isRequired, // func(stepSlug, deltaId, startRowInclusive, endRowExclusive) => Promise[Array[Object] or error]
    workflowIdOrSecretId: propTypes.workflowId.isRequired,
    stepBeforeError: PropTypes.shape({
      id: PropTypes.number.isRequired,
      deltaId: PropTypes.number, // or null -- it may not be rendered
      status: PropTypes.oneOf(['ok', 'busy', 'unreachable']).isRequired, // can't be 'error'
      columns: PropTypes.arrayOf(
        PropTypes.shape({
          name: PropTypes.string.isRequired,
          type: PropTypes.oneOf(['text', 'number', 'timestamp']).isRequired
        }).isRequired
      ), // or null
      nRows: PropTypes.number // or null
    }), // or null if no error
    step: PropTypes.shape({
      id: PropTypes.number.isRequired,
      htmlOutput: PropTypes.bool.isRequired,
      status: PropTypes.oneOf(['ok', 'busy', 'error', 'unreachable'])
        .isRequired,
      deltaId: PropTypes.number, // or null if not yet rendered
      columns: PropTypes.arrayOf(
        PropTypes.shape({
          name: PropTypes.string.isRequired,
          type: PropTypes.oneOf(['text', 'number', 'timestamp']).isRequired
        }).isRequired
      ), // or null
      nRows: PropTypes.number // or null
    }), // or null if no selection
    isPublic: PropTypes.bool.isRequired,
    isReadOnly: PropTypes.bool.isRequired
  }

  /**
   * Return the Step we want to render for the user.
   *
   * This will _never_ be an "error"-status Step. If there's an error, we
   * want the user to see the input. (This component will also render a notice
   * saying it's showing the input.)
   */
  get stepForTable () {
    const { stepBeforeError, step } = this.props

    if (stepBeforeError) {
      // We're focused on an error module. The user wants to see its _input_ to
      // debug it.
      return stepBeforeError
    } else if (step && step.status !== 'error') {
      return step
    } else {
      // Either there's no selected Step, or the selected Step has
      // status === 'error' and it's the first in the tab. Either way, we want
      // to render a "placeholder" table.
      return null
    }
  }

  renderOutputIFrame () {
    // Always show _this_ module's iframe. If this module has status 'error'
    // and it's the Python console, the iframe contains the stack trace. If
    // we showed the _input_ module's iframe we wouldn't render the stack
    // trace.

    const { step, workflowIdOrSecretId, isPublic } = this.props

    const moduleSlug = (step && step.htmlOutput) ? step.module : null
    const stepSlug = step ? step.slug : null
    const stepId = step ? step.id : null
    const deltaId = step ? step.deltaId : null

    // This iframe holds the module HTML output, e.g. a visualization.
    // We leave the component around even when there is no HTML because of
    // our solution to https://www.pivotaltracker.com/story/show/159637930:
    // <OutputIframe> fires resize events, even if it doesn't render
    // any <iframe>.
    return (
      <OutputIframe
        workflowIdOrSecretId={workflowIdOrSecretId}
        isPublic={isPublic}
        stepId={stepId}
        stepSlug={stepSlug}
        moduleSlug={moduleSlug}
        deltaId={deltaId}
      />
    )
  }

  render () {
    const { isReadOnly, loadRows, step, stepBeforeError, workflowIdOrSecretId } = this.props
    const stepForTable = this.stepForTable
    const className =
      'outputpane module-' + (step ? step.status : 'unreachable')

    return (
      <div className={className}>
        {this.renderOutputIFrame()}
        {stepBeforeError
          ? (
            <p key='error' className='showing-input-because-error'>
              <Trans id='js.WorkflowEditor.OutputPane.showingInput.becauseError'>
                This was the data that led to an error. Please correct the error
                in the left pane.
              </Trans>
            </p>
            )
          : null}
        <DelayedTableSwitcher
          key='table'
          workflowIdOrSecretId={workflowIdOrSecretId}
          stepSlug={stepForTable ? stepForTable.slug : null}
          stepId={stepForTable ? stepForTable.id : null}
          status={stepForTable ? stepForTable.status : null}
          deltaId={stepForTable ? stepForTable.deltaId : null}
          columns={stepForTable ? stepForTable.columns : null}
          nRows={stepForTable ? stepForTable.nRows : null}
          isReadOnly={isReadOnly}
          loadRows={loadRows}
        />
      </div>
    )
  }
}

function stepStatus (step) {
  // TODO don't copy/paste from Step.js
  if (!step) {
    return null
  } else if (
    // We've just sent an HTTP request and not received a response.
    // (This happens after the user clicks to change something -- or clicks
    // "fetch" -- and before the server updates the status.)
    step.nClientRequests > 0 ||
    // The module is performing a fetch
    step.is_busy ||
    // Step is a placeholder? TODO verify this can actually happen
    !step.output_status ||
    // Step is rendering
    step.last_relevant_delta_id !== step.cached_render_result_delta_id
  ) {
    return 'busy'
  } else {
    return step.output_status
  }
}

function mapStateToProps (state) {
  const { workflow, steps, tabs, modules, selectedPane } = state
  const tabSlug = selectedPane.tabSlug
  const tab = tabs[tabSlug]
  const stepArray = tab.step_ids.map(id => steps[String(id)])

  const stepIndex = tab.selected_step_position
  let step = stepArray[stepIndex] || null
  let stepBeforeError

  const status = step ? stepStatus(step) : 'busy'

  if (step === null && tab.step_ids[stepIndex]) {
    // We're pointing at a "placeholder" module: its id isn't in steps.
    // HACK: for now, we want OutputPane to render something different (it needs
    // to give TableSwitcher a "busy"-status Step).
    step = {
      id: -1,
      slug: null,
      module_id_name: '',
      status: 'busy',
      cached_render_result_delta_id: null,
      columns: null,
      nRows: null
    }
  }

  // If we're pointing at a module that output an error, we'll want to display
  // its _input_ (the previous module's output) to help the user fix things.
  if (status === 'error' && tab.selected_step_position > 0) {
    const lastGood = stepArray[stepIndex - 1]
    stepBeforeError = {
      id: lastGood.id,
      slug: lastGood.slug,
      deltaId: lastGood.cached_render_result_delta_id,
      status: stepStatus(lastGood),
      columns: lastGood.output_columns,
      nRows: lastGood.output_n_rows
    }
  }

  return {
    workflowIdOrSecretId: selectWorkflowIdOrSecretId(state),
    step: step
      ? {
          id: step.id,
          slug: step.slug,
          module: step.module,
          htmlOutput: modules[step.module]
            ? modules[step.module].has_html_output
            : false,
          status,
          deltaId: step.cached_render_result_delta_id,
          columns: step.output_columns,
          nRows: step.output_n_rows
        }
      : null,
    stepBeforeError,
    isPublic: workflow.public,
    isReadOnly: selectIsReadOnly(state)
  }
}

function mapDispatchToProps (dispatch) {
  return {
    loadRows: (stepSlug, deltaId, startRow, endRow) => {
      return dispatch((_, __, api) => {
        return api.getStepResultTableSlice(stepSlug, deltaId, startRow, endRow)
      })
    }
  }
}

export default connect(mapStateToProps, mapDispatchToProps)(OutputPane)
