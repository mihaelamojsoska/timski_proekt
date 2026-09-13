import { useEffect, useState } from 'react';
import { AppShell } from '../components/layout/AppShell';
import { CourseNavSidebar } from '../components/courses/CourseNavSidebar';
import { useAuth } from '../context/AuthContext';
import { listAllCourses, approveCourse, rejectCourse } from '../api/admin';
import { deleteCourse } from '../api/courses';
import type { AdminCourseOut } from '../types/course';
import { StubPage } from './StubPage';

type StatusFilter = 'pending' | 'approved' | 'rejected' | 'all';

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'All' },
];

function StatusBadge({ status }: { status: AdminCourseOut['status'] }) {
  const label = status === 'pending' ? 'Pending' : status === 'approved' ? 'Approved' : 'Rejected';
  return <span className={`status-badge status-${status}`}>{label}</span>;
}

export function AdminPage() {
  const { user } = useAuth();
  const [filter, setFilter] = useState<StatusFilter>('pending');
  const [courses, setCourses] = useState<AdminCourseOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [reasonDraft, setReasonDraft] = useState<Record<number, string>>({});

  const load = (status: StatusFilter) => {
    listAllCourses(status)
      .then((data) => {
        setCourses(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load courses'));
  };

  useEffect(() => {
    if (user?.role === 'admin') load(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, filter]);

  if (user && user.role !== 'admin') {
    return <StubPage title="Admin" description="This area is only available to admin accounts." />;
  }

  const handleApprove = async (id: number) => {
    setBusyId(id);
    try {
      await approveCourse(id);
      load(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve course');
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (id: number) => {
    const reason = (reasonDraft[id] || '').trim();
    if (!reason) {
      setError('Add a reason before rejecting, so the professor knows what to fix.');
      return;
    }
    setBusyId(id);
    try {
      await rejectCourse(id, reason);
      load(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject course');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (!window.confirm(`Permanently delete "${name}"? This removes its materials and purchase records too - there's no undo.`)) {
      return;
    }
    setBusyId(id);
    try {
      await deleteCourse(id);
      load(filter);
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
            <h1>Course approvals</h1>
            <p className="page-subtitle">
              Courses submitted by users wait here until you approve or reject them. Approved courses appear
              immediately in the Marketplace; rejected ones stay hidden and the submitter sees your reason on
              their "My courses" page. Delete permanently removes a course regardless of status - no undo.
            </p>
          </div>

          <div className="filter-row">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                className={`filter-btn${filter === f.value ? ' active' : ''}`}
                onClick={() => setFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {error && <div className="msg-error" style={{ marginTop: 20 }}>{error}</div>}

          {courses === null && !error && <div className="empty" style={{ marginTop: 24 }}>Loading…</div>}

          {courses !== null && courses.length === 0 && (
            <div className="empty" style={{ marginTop: 24 }}>Nothing here right now.</div>
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
                  <div className="sugg-tag">{c.code || c.slug}{c.semester ? ` · ${c.semester}` : ''}</div>
                  <div className="sugg-q">{c.name}</div>
                  {c.submitted_by_name && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                      Submitted by {c.submitted_by_name}
                    </div>
                  )}
                </div>
                <StatusBadge status={c.status} />
              </div>

              {c.description && <p style={{ color: 'var(--muted)', fontSize: 13, margin: 0 }}>{c.description}</p>}

              {c.status === 'rejected' && c.rejection_reason && (
                <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>
                  <strong>Rejection reason:</strong> {c.rejection_reason}
                </div>
              )}

              {c.materials.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div className="sugg-tag">Materials ({c.materials.length})</div>
                  {c.materials.map((m) => (
                    <a
                      key={m.id}
                      href={m.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: 12.5, color: 'var(--ink)', textDecoration: 'underline' }}
                    >
                      {m.title}
                      {m.category ? ` · ${m.category}` : ''}
                    </a>
                  ))}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {c.status === 'pending' && (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={busyId === c.id}
                      onClick={() => handleApprove(c.id)}
                    >
                      Approve
                    </button>
                    <input
                      type="text"
                      className="auth-input"
                      style={{ flex: 1, minWidth: 200 }}
                      placeholder="Reason for rejecting (required to reject)"
                      value={reasonDraft[c.id] || ''}
                      onChange={(e) => setReasonDraft((prev) => ({ ...prev, [c.id]: e.target.value }))}
                    />
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={busyId === c.id}
                      onClick={() => handleReject(c.id)}
                    >
                      Reject
                    </button>
                  </>
                )}
                <button
                  type="button"
                  className="btn btn-danger"
                  style={{ marginLeft: c.status === 'pending' ? 0 : 'auto' }}
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
