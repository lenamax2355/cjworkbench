import ReactDOM from 'react-dom'
import BillingPage from '../settings/BillingPage'
import WorkbenchAPI from '../WorkbenchAPI'
import InternationalizedPage from '../i18n/InternationalizedPage'

const api = new WorkbenchAPI(null) // no websocket
const { user } = window.initState

ReactDOM.render(
  <InternationalizedPage>
    <BillingPage api={api} user={user} />
  </InternationalizedPage>,
  document.getElementById('root')
)

// Start Intercom, if we're that sort of installation
if (window.APP_ID) {
  window.Intercom('boot', {
    app_id: window.APP_ID,
    email: window.initState.user.email,
    user_id: window.initState.user.id,
    alignment: 'right',
    horizontal_padding: 20,
    vertical_padding: 20
  })
}
