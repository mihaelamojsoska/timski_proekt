import { cloneElement, isValidElement, useEffect, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useCollapsed } from '../../hooks/useCollapsed';
import { ChevronIcon } from '../icons';

interface AppShellProps {
  sidebar: ReactNode;
  children: ReactNode;
  rightSidebar?: ReactNode;
  /** Only meaningful when rightSidebar is passed - controlled by the caller
   * since its toggle button lives wherever makes sense for that page (e.g.
   * ChatPage's own masthead), not inside this generic shell. */
  rightSidebarCollapsed?: boolean;
  /** Same caller-owned toggle as above - passed through so the backdrop,
   * close button, and swipe gesture (all mobile-only, see globals.css) can
   * close the panel, matching the left sidebar's mobile behavior. */
  onRightSidebarToggle?: () => void;
}

// How close to the screen edge a swipe has to START to count as "opening"
// a panel - keeps an ordinary swipe/scroll in the middle of the page from
// accidentally triggering it. How far it has to travel before counting as
// a deliberate swipe at all (vs. a tap or a mostly-vertical scroll).
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
  // Separate from leftCollapsed (which persists the desktop icon-only
  // preference) - this only controls whether the sidebar overlay is open
  // on narrow/mobile screens, and always starts closed.
  const [mobileOpen, setMobileOpen] = useState(false);

  // Edge-swipe gestures, mobile only (touch events never fire from a mouse):
  // swipe right from the left edge opens the left menu, swipe left from the
  // right edge opens the sources panel, and swiping back the other way
  // closes whichever one is currently open.
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
  // persisted desktop icon-only preference - a narrow icon rail floating in
  // an otherwise-empty 80vw panel makes no sense once it's already an
  // overlay rather than competing for space with the main content.
  const sidebarContent = isValidElement(sidebar)
    ? cloneElement(sidebar as ReactElement<{ collapsed?: boolean }>, {
        collapsed: mobileOpen ? false : leftCollapsed,
      })
    : sidebar;

  return (
    <div className="app paper-grain">
      {/* Only shown while the mobile sidebar is CLOSED - once open, the
         sidebar's own inline arrow below (styled like desktop's, next to
         the "LearnWise" brand) takes over as the close control, sitting
         inline instead of floating over page content. */}
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
