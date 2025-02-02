/* global describe, it, expect, jest */
import { mountWithI18n } from '../i18n/test-utils'
import { Provider } from 'react-redux'
import { mockStore, tick } from '../test-utils'
import { generateSlug } from '../utils'
import TableView from './TableView'

jest.mock('../utils')

// Ugly hack - let us setProps() on the mounted component
// See https://github.com/airbnb/enzyme/issues/947
//
// The problem is: we _must_ use mount() and not shallow() because we want to
// test TableView's componentDidMount() behavior (the loading of data). And
// since one of TableView's descendents uses react-redux, we must use a
// <Provider> to make mount() succeed.
//
// We want to test setProps(), because we do things when props change. But
// mounted components' setProps() only work on the root component.
//
// So here's a root component that handles setProps() and the <Provider>, all
// in one.
function ConnectedTableView (props) {
  props = { ...props } // clone
  const store = props.store
  delete props.store

  return (
    <Provider store={store}>
      <TableView {...props} />
    </Provider>
  )
}

describe('TableView', () => {
  const wrapper = (store, extraProps = {}) => {
    // mock store for <SelectedRowsActions>, a descendent
    if (store === null) {
      store = mockStore({
        modules: {},
        workflow: {
          steps: [99, 100, 101]
        }
      })
    }

    return mountWithI18n(
      <ConnectedTableView
        store={store}
        isReadOnly={false}
        workflowIdOrSecretId={123}
        stepSlug='step-1'
        stepId={100}
        deltaId={1}
        status='ok'
        loadRows={makeRenderResponse(0, 3, 5)}
        columns={[
          { name: 'a', type: 'number', format: '{:,d}' },
          { name: 'b', type: 'number', format: '{:,d}' },
          { name: 'c', type: 'number', format: '{:,d}' }
        ]}
        nRows={2}
        {...extraProps}
      />
    )
  }

  // Mocks json response (promise) returning part of a larger table
  function makeRenderResponse (start, end, totalRows) {
    const nRows = end - start - 1
    const data = {
      start_row: start,
      end_row: end,
      rows: Array(nRows).fill({ a: 1, b: 2, c: 3 })
    }
    return jest.fn(() => Promise.resolve(data))
  }

  it('reorders columns', async () => {
    // integration-test style -- these moving parts tend to rely on one another
    // lots: ignoring workflow-reducer means tests miss bugs.
    const api = { addStep: jest.fn(() => Promise.resolve(null)) }
    generateSlug.mockImplementationOnce(prefix => prefix + 'X')
    const store = mockStore(
      {
        workflow: {
          tab_slugs: ['tab-1']
        },
        tabs: {
          'tab-1': { step_ids: [2, 3], selected_step_position: 0 }
        },
        steps: {
          2: { slug: 'step-2', tab_slug: 'tab-1' },
          3: {}
        },
        modules: {
          reordercolumns: {}
        }
      },
      api
    )

    const tree = wrapper(store, { stepSlug: 'step-2', stepId: 2 })
    tree
      .find('DataGrid')
      .instance()
      .handleDropColumnIndexAtIndex(0, 2)

    await tick()

    expect(api.addStep).toHaveBeenCalledWith(
      'tab-1',
      'step-X',
      'reordercolumns',
      1,
      {
        'reorder-history': JSON.stringify([{ column: 'a', to: 1, from: 0 }])
      }
    )

    await tick() // let things settle
  })

  it('edits cells', async () => {
    // integration-test style -- these moving parts tend to rely on one another
    // lots: ignoring workflow-reducer means tests miss bugs.
    const api = {
      addStep: jest.fn().mockImplementation(() => Promise.resolve(null))
    }
    generateSlug.mockImplementationOnce(prefix => prefix + 'X')
    const store = mockStore(
      {
        workflow: {
          tab_slugs: ['tab-1']
        },
        tabs: {
          'tab-1': { step_ids: [2, 3], selected_step_position: 0 }
        },
        steps: {
          2: { slug: 'step-2', tab_slug: 'tab-1' },
          3: {}
        },
        modules: {
          editcells: {}
        }
      },
      api
    )

    const tree = wrapper(store, { stepSlug: 'step-2', stepId: 2 })
    await tick() // load data
    tree
      .find('DataGrid')
      .instance()
      .handleGridRowsUpdated({
        fromRow: 0,
        fromRowData: { a: 'a1', b: 'b1', c: 'c1' },
        toRow: 0,
        cellKey: 'b',
        updated: { b: 'b2' }
      })

    expect(api.addStep).toHaveBeenCalledWith(
      'tab-1',
      'step-X',
      'editcells',
      1,
      {
        celledits: [{ row: 0, col: 'b', value: 'b2' }]
      }
    )

    await tick() // let things settle
  })

  it('blanks table when no module id', () => {
    const tree = wrapper(null, {}, { stepSlug: null, stepId: undefined })
    expect(tree.find('.outputpane-header')).toHaveLength(1)
    expect(tree.find('.outputpane-data')).toHaveLength(1)
    // And we can see it did not call api.render, because that does not exist
  })

  // TODO move this to TableSwitcher.js/DelayedTableSwitcher.js:
  // it('shows a spinner on initial load', async () => {
  //  const testData = {
  //    start_row: 0,
  //    end_row: 2,
  //    rows: [
  //      { a: 1, b: 2, c: 3 },
  //      { a: 4, b: 5, c: 6 }
  //    ]
  //  }

  //  const tree = wrapper(null, { loadData: jest.fn(() => Promise.resolve(testData)) })

  //  expect(tree.find('#spinner-container-transparent')).toHaveLength(1)
  //  await tick()
  //  tree.update()
  //  expect(tree.find('#spinner-container-transparent')).toHaveLength(0)
  // })

  it('renders a message (and no table) when >100 columns', async () => {
    // This is because react-data-grid is so darned slow to render columns
    const columns = []
    for (let i = 0; i < 101; i++) {
      columns[i] = { name: String(i), type: 'number' }
    }

    const loadData = jest.fn()
    const tree = wrapper(null, { loadData, columns })

    const overlay = tree.find('.overlay')
    expect(overlay).toHaveLength(1)
    expect(loadData).not.toHaveBeenCalled()
  })
})
