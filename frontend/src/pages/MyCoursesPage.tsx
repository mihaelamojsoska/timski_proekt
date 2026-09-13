import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import { CourseNavSidebar } from '../components/courses/CourseNavSidebar';
import { listMyCourses, deleteCourse } from '../api/courses';
import type { AdminCourseOut } from '../types/course';

function formatPrice(cents: number): string {
  return cents > 0 ? `€${(cents / 100).toFixed(2)}` : 'Free';
}

function StatusBadge({ status }: { status: AdminCourseOut['status'] }) {
  const label = status === 'pending' ? 'Pending review' : status === 'approved' ? 'Approved' : 'Rejected';
  return <span className={`status-badge status-${status}`}>{label}</span>;
}

/** Every course the logged-in user has submitted, whatever its review
 * status - the only place in the app that surfaces an admin's rejection
 * reason back to whoever submitted the course. Also where a professor can
 * delete one of their own Marketplace listings (approved, pending, or
 * rejected) without needing an admin to do it for them. */
export function MyCoursesPage() {
  const [courses, setCourses] = useState<AdminCourseOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = () => {
    listMyCourses()
      .then((data) => {
        setCourses(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load your courses'));
  };

  useEffect(() => {
    load();
  }, []);

  const handleDelete = async (id: number, name: string) => {
    if (!window.confirm(`Permanently delete "${name}"? This removes its materials and purchase records too - there's no undo.`)) {
      return;
    }
    setBusyId(id);
    try {
      await deleteCourse(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete course');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <AppShell sidebar={<CourseNavSidebar />}>
      <div className="body">
        <div className="page-container">
          <div className="page-header">
            <h1>My courses</h1>
            <p className="page-subtitle">
              Everything you've submitted, whatever its review status - approved ones are live in the
              Marketplace, pending ones are waiting on an admin, and rejected ones show why. You can delete any
              of your own submissions here.
            </p>
          </div>

          {error && <div className="msg-error" style={{ marginTop: 20 }}>{error}</div>}

          {courses === null && !error && <div className="empty" style={{ marginTop: 24 }}>Loading…</div>}

          {courses !== null && courses.length === 0 && (
            <div className="empty" style={{ marginTop: 24 }}>
              You haven't submitted any courses yet. Head to the{' '}
              <Link to="/marketplace/submit">submission form</Link> to add one.
            </div>
          )}

          <div className="card-stack">
            {(courses || []).map((c) => (
            <div
              key={c.id}
              className="sugg"
              style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10, cursor: 'default' }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div className="sugg-tag">
                    {c.code || c.slug}
                    {c.semester ? ` · ${c.semester}` : ''} · {formatPrice(c.price_cents)}
                  </div>
                  <div className="sugg-q">
                    {c.status === 'approved' ? <Link to={`/marketplace/${c.id}`}>{c.name}</Link> : c.name}
                  </div>
                </div>
                <StatusBadge status={c.status} />
              </div>

              {c.description && <p style={{ color: 'var(--muted)', fontSize: 13, margin: 0 }}>{c.description}</p>}

              {c.status === 'rejected' && c.rejection_reason && (
                <div className="msg-error" style={{ margin: 0 }}>
                  <strong>Why it was rejected:</strong> {c.rejection_reason}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>{c.materials.length} material(s) attached</div>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busyId === c.id}
                  onClick={() => handleDelete(c.id, c.name)}
                >
                  Delete
                </button>
              </div>
            </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
