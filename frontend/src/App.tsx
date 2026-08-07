import { Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import Dashboard from './pages/Dashboard'
import Inbox from './pages/Inbox'
import Invoices from './pages/Invoices'
import Agents from './pages/Agents'
import Login from './pages/Login'
import { Approvals, Audit, Exceptions, Governance, Payments, SLA, Skills, Suppliers } from './pages/Misc'
import { useSession } from './store'
import { Toast } from './components/ui'

export default function App() {
  const { user, toast, clearToast } = useSession()

  if (!user) {
    return (
      <>
        <Login />
        {toast && <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />}
      </>
    )
  }

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/invoices" element={<Invoices />} />
        <Route path="/exceptions" element={<Exceptions />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/payments" element={<Payments />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/sla" element={<SLA />} />
        <Route path="/suppliers" element={<Suppliers />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/governance" element={<Governance />} />
        <Route path="*" element={<Dashboard />} />
      </Routes>
    </Shell>
  )
}
