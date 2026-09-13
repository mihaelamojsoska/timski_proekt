import { cloneElement, isValidElement, useEffect, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useCollapsed } from '../../hooks/useCollapsed';
import { ChevronIcon } from '../icons';

interface AppShellProps {
  sidebar: ReactNode;
  children: ReactNode;
  rightSidebar?: ReactNode;
  rightSidebarCollapsed?: boolean;
  onRightSidebarToggle?: () => void;
}

const EDGE_ZONE_PX = 24;
const SWIPE_THRESHOLD_PX = 50;

export function AppShell({
  sidebar,
  children,
  rightSidebar,
  rightSidebarCollapsed,
  onRightSidebarToggle,
}: AppShellProps) {
  const [leftCollapsed, toggleLeft] = useCollapsed('lw_sidebar_left');
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    let startX = 0;
    let startY = 0;
    let tracking = false;

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      tracking = true;
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (!tracking) return;
      tracking = false;
      const endX = e.changedTouches[0].clientX;
      const endY = e.changedTouches[0].clientY;
      const dx = endX - startX;
      const dy = endY - startY;
      if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) < Math.abs(dy)) return;

      if (mobileOpen) {
        if (dx < 0) setMobileOpen(false);
        return;
      }
      if (rightSidebar && !rightSidebarCollapsed) {
        if (dx > 0) onRightSidebarToggle?.();
        return;
      }
      if (dx > 0 && startX < EDGE_ZONE_PX) {
        setMobileOpen(true);
      } else if (dx < 0 && rightSidebar && startX > window.innerWidth - EDGE_ZONE_PX) {
        onRightSidebarToggle?.();
      }
    };

    window.addEventListener('touchstart', onTouchStart, { passive: true });
    window.addEventListener('touchend', onTouchEnd, { passive: true });
    return () => {
      window.removeEventListener('touchstart', onTouchStart);
      window.removeEventListener('touchend', onTouchEnd);
    };
  }, [mobileOpen, rightSidebar, rightSidebarCollapsed, onRightSidebarToggle]);

  // On the mobile overlay, always show the full sidebar regardless of the
  // persisted desktop icon-only preference.
  const sidebarContent = isValidElement(sidebar)
    ? cloneElement(sidebar as ReactElement<{ collapsed?: boolean }>, {
        collapsed: mobileOpen ? false : leftCollapsed,
      })
    : sidebar;

  return (
    <div className="app paper-grain">
      {/* Only shown while the mobile sidebar is CLOSED - once open, the
         sidebar's own inline arrow below (styled like desktop's) takes
         over as the close control, sitting inline instead of floating
         over page content. */}
      {!mobileOpen && (
        <button
          type="button"
          className="mobile-nav-toggle"
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          title="Open menu"
        >
          <ChevronIcon />
        </button>
      )}
      {mobileOpen && <div className="mobile-nav-backdrop" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar-left${leftCollapsed ? ' collapsed' : ''}${mobileOpen ? ' mobile-open' : ''}`}>
        {sidebarContent}
        <button
          type="button"
          className="sidebar-collapse-btn"
          onClick={mobileOpen ? () => setMobileOpen(false) : toggleLeft}
          aria-label={mobileOpen ? 'Close menu' : leftCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={mobileOpen ? 'Close menu' : leftCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronIcon flip={mobileOpen ? false : leftCollapsed} />
        </button>
      </aside>
      <main>{children}</main>
      {rightSidebar && !rightSidebarCollapsed && (
        <div className="sidebar-right-backdrop" onClick={onRightSidebarToggle} />
      )}
      {rightSidebar && (
        <aside className={`sidebar-right${rightSidebarCollapsed ? ' collapsed' : ''}`}>
          {!rightSidebarCollapsed && (
            <>
              <button
                type="button"
                className="sidebar-right-close-btn"
                onClick={onRightSidebarToggle}
                aria-label="Close sources panel"
                title="Close sources panel"
              >
                <ChevronIcon flip />
              </button>
              {rightSidebar}
            </>
          )}
        </aside>
      )}
    </div>
  );
}
