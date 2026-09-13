import { cloneElement, isValidElement, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useCollapsed } from '../../hooks/useCollapsed';
import { ChevronIcon } from '../icons';

/** Plain hamburger/close icon, inline rather than in icons.tsx since it's
 * only ever used here for the mobile nav toggle. */
function MenuIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="6" y1="6" x2="18" y2="18" />
        <line x1="18" y1="6" x2="6" y2="18" />
      </svg>
    );
  }
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

interface AppShellProps {
  sidebar: ReactNode;
  children: ReactNode;
  rightSidebar?: ReactNode;
  /** Only meaningful when rightSidebar is passed - controlled by the caller
   * since its toggle button lives wherever makes sense for that page (e.g.
   * ChatPage's own masthead), not inside this generic shell. */
  rightSidebarCollapsed?: boolean;
  /** Same caller-owned toggle as above - passed through so the backdrop
   * (shown only on narrow screens, see globals.css) can close the panel
   * on tap, matching the left sidebar's mobile behavior. */
  onRightSidebarToggle?: () => void;
}

export function AppShell({
  sidebar,
  children,
  rightSidebar,
  rightSidebarCollapsed,
  onRightSidebarToggle,
}: AppShellProps) {
  const [leftCollapsed, toggleLeft] = useCollapsed('lw_sidebar_left');
  // Separate from leftCollapsed (which persists the desktop icon-only
  // preference) - this only controls whether the sidebar overlay is open
  // on narrow/mobile screens, and always starts closed.
  const [mobileOpen, setMobileOpen] = useState(false);

  const sidebarContent = isValidElement(sidebar)
    ? cloneElement(sidebar as ReactElement<{ collapsed?: boolean }>, { collapsed: leftCollapsed })
    : sidebar;

  return (
    <div className="app paper-grain">
      <button
        type="button"
        className="mobile-nav-toggle"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
        title={mobileOpen ? 'Close menu' : 'Open menu'}
      >
        <MenuIcon open={mobileOpen} />
      </button>
      {mobileOpen && <div className="mobile-nav-backdrop" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar-left${leftCollapsed ? ' collapsed' : ''}${mobileOpen ? ' mobile-open' : ''}`}>
        {sidebarContent}
        <button
          type="button"
          className="sidebar-collapse-btn"
          onClick={toggleLeft}
          aria-label={leftCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={leftCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronIcon flip={leftCollapsed} />
        </button>
      </aside>
      <main>{children}</main>
      {rightSidebar && !rightSidebarCollapsed && (
        <div className="sidebar-right-backdrop" onClick={onRightSidebarToggle} />
      )}
      {rightSidebar && (
        <aside className={`sidebar-right${rightSidebarCollapsed ? ' collapsed' : ''}`}>
          {!rightSidebarCollapsed && rightSidebar}
        </aside>
      )}
    </div>
  );
}
