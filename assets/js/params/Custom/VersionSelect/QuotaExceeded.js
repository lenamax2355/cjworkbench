import React from 'react'
import PropTypes from 'prop-types'

const numberFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

function groupAutofetches (autofetches) {
  const groups = {} // workflow-id => { workflow, nFetchesPerDay, autofetches }
  for (const autofetch of autofetches) {
    const groupId = String(autofetch.workflow.id)
    if (!(groupId in groups)) {
      groups[groupId] = {
        workflow: autofetch.workflow,
        nFetchesPerDay: 0,
        autofetches: []
      }
    }
    const group = groups[groupId]
    group.nFetchesPerDay += 86400 / autofetch.wfModule.fetchInterval
    group.autofetches.push(autofetch)
  }

  return Object.values(groups).sort((a, b) => b.nFetchesPerDay - a.nFetchesPerDay || a.workflow.name.localeCompare(b.workflow.name))
}

const QuotaExceeded = React.memo(function QuotaExceeded ({ workflowId, wfModuleId, maxFetchesPerDay, nFetchesPerDay, autofetches }) {
  const autofetchGroups = groupAutofetches(autofetches)

  return (
    <div className='quota-exceeded'>
      <h5>Not set — too many updates</h5>
      <p>
        You're a keener! You're requesting{' '}
        <strong className='n-fetches-per-day'>{Math.ceil(numberFormatter.format(nFetchesPerDay))}</strong>{' '}
        updates per day across all your workflows. Your daily limit is{' '}
        <strong className='max-fetches-per-day'>{numberFormatter.format(maxFetchesPerDay)}</strong>.
      </p>
      <p>
        Here are the steps that count against your limit.
        Adjust their update times or set them to manual, then click
        "Retry" above.
      </p>
      <table>
        <thead>
          <tr>
            <th className='n-fetches-per-day'>#/day</th>
            <th className='step'>Workflow</th>
            <th className='open' />
          </tr>
        </thead>
        <tbody>
          {autofetchGroups.map(({ workflow, nFetchesPerDay, autofetches }) => (
            <tr key={workflow.id}>
              <td className='n-fetches-per-day'>
                {numberFormatter.format(nFetchesPerDay)}
              </td>
              <td className='workflow'>
                <div className='workflow'>
                  {workflowId === workflow.id ? (
                    <div className='this-workflow'>(This workflow)</div>
                  ) : (
                    <div className='other-workflow'>
                      {workflow.name}{' '}
                      <a className='edit' target='_blank' href={`/workflows/${workflow.id}/`}>
                        Edit workflow <i className='icon-edit'></i>
                      </a>
                    </div>
                  )}
                </div>
                <ul className='steps'>
                  {autofetches.map(({ tab, wfModule }) => (
                    <li key={wfModule.id}>
                      {workflowId === workflow.id && wfModuleId === wfModule.id ? (
                        <>(You asked for this step to make {numberFormatter.format(86400 / wfModule.fetchInterval)} updates per day.)</>
                      ) : (
                        <>Step {wfModule.order + 1} on {tab.name} makes {numberFormatter.format(86400 / wfModule.fetchInterval)} updates per day.</>
                      )}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Need a higher limit?
        Please email us at <a href='mailto:hello@workbenchdata.com' target='_blank'>hello@workbenchdata.com</a> and describe what you're working on.
      </p>
    </div>
  )
})
QuotaExceeded.propTypes = {
  maxFetchesPerDay: PropTypes.number.isRequired,
  nFetchesPerDay: PropTypes.number.isRequired,
  autofetches: PropTypes.arrayOf(PropTypes.shape({
    workflow: PropTypes.shape({
      id: PropTypes.number.isRequired,
      name: PropTypes.string.isRequired
    }).isRequired,
    tab: PropTypes.shape({
      name: PropTypes.string.isRequired,
    }).isRequired,
    wfModule: PropTypes.shape({
      id: PropTypes.number.isRequired,
      fetchInterval: PropTypes.number.isRequired,
    })
  }).isRequired).isRequired
}
export default QuotaExceeded
