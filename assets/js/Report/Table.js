import { useCallback, useMemo } from 'react'
import PropTypes from 'prop-types'
import propTypes from '../propTypes'
import { connect } from 'react-redux'
import BigTable from '../BigTable'
import useTiles from '../BigTable/useTiles'
import { columnToCellFormatter } from './CellFormatters2'

function ColumnHeader ({ name, type }) {
  return (
    <div className='column-header'>
      <div className='column-name'>{name}</div>
      <div className='column-type'>{type}</div>
    </div>
  )
}

function buildColumnHeaderComponent ({ name, type }) {
  return () => <ColumnHeader name={name} type={type} />
}

function Table ({
  workflowIdOrSecretId,
  stepSlug,
  deltaId,
  nRows,
  columns,
  nRowsPerTile,
  nColumnsPerTile
}) {
  const nTileRows = Math.ceil(nRows / nRowsPerTile)
  const nTileColumns = Math.ceil(columns.length / nColumnsPerTile)
  const fetchTile = useCallback(
    (tileRow, tileColumn, fetchOptions) => {
      const url = `/workflows/${workflowIdOrSecretId}/tiles/${stepSlug}/delta-${deltaId}/${tileRow},${tileColumn}.json`
      return global.fetch(url, fetchOptions)
    },
    [workflowIdOrSecretId, stepSlug, deltaId]
  )
  const { sparseTileGrid, setWantedTileRange } = useTiles({
    fetchTile,
    nTileRows,
    nTileColumns
  })
  const bigColumns = useMemo(
    () =>
      columns.map(column => ({
        ...column,
        width: 180,
        headerComponent: buildColumnHeaderComponent(column),
        valueComponent: columnToCellFormatter(column)
      })),
    [columns]
  )

  return (
    <BigTable
      sparseTileGrid={sparseTileGrid}
      nRows={nRows}
      columns={bigColumns}
      nRowsPerTile={nRowsPerTile}
      nColumnsPerTile={nColumnsPerTile}
      setWantedTileRange={setWantedTileRange}
    />
  )
}
Table.propTypes = {
  workflowIdOrSecretId: propTypes.workflowId.isRequired,
  stepSlug: PropTypes.string.isRequired,
  deltaId: PropTypes.number.isRequired,
  nRows: PropTypes.number.isRequired,
  columns: PropTypes.array.isRequired,
  nRowsPerTile: PropTypes.number.isRequired,
  nColumnsPerTile: PropTypes.number.isRequired
}

function mapStateToProps (state, { stepSlug }) {
  const step = Object.values(state.steps).filter(
    step => step.slug === stepSlug
  )[0]
  return {
    deltaId: step.cached_render_result_delta_id,
    nRows: step.output_n_rows,
    columns: step.output_columns,
    nRowsPerTile: state.settings.bigTableRowsPerTile,
    nColumnsPerTile: state.settings.bigTableColumnsPerTile
  }
}

export default connect(mapStateToProps)(Table)
