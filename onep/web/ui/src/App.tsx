import { Outlet } from "react-router";
import { AppShell } from "./components/shell";

export default function App() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
