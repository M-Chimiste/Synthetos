import { Link, useRouterState } from "@tanstack/react-router";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/charters", label: "Charters" },
  { to: "/events", label: "Events" },
  { to: "/patterns", label: "Patterns" },
  { to: "/skills", label: "Skills" },
] as const;

export default function Layout({ children }: { children: React.ReactNode }) {
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  return (
    <div className="flex min-h-screen bg-gray-50 text-gray-900">
      {/* Sidebar */}
      <aside className="flex w-56 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-5 py-4">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            Synthetos
          </Link>
        </div>
        <nav className="flex-1 px-3 py-4">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const active =
                item.to === "/"
                  ? currentPath === "/"
                  : currentPath.startsWith(item.to);
              return (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    className={`block rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      active
                        ? "bg-gray-100 text-gray-900"
                        : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-gray-200 px-5 py-3 text-xs text-gray-400">
          Phase 0
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
