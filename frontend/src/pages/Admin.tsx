import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

interface AdminUser {
  id: string;
  username: string;
  created_at: string;
  poll_count: number;
  is_admin: boolean;
}
interface AdminPoll {
  id: string;
  slug: string;
  title: string;
  creator: string | null;
  status: string;
  ballot_count: number;
}
interface Page {
  total: number;
  page: number;
  per_page: number;
}

export default function Admin() {
  const { user } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [polls, setPolls] = useState<AdminPoll[]>([]);
  const [uPage, setUPage] = useState(1);
  const [pPage, setPPage] = useState(1);
  const [uTotal, setUTotal] = useState(0);
  const [pTotal, setPTotal] = useState(0);
  const perPage = 25;

  const loadUsers = (page: number) =>
    api
      .get<Page & { users: AdminUser[] }>(`/admin/users?page=${page}&per_page=${perPage}`)
      .then((d) => {
        setUsers(d.users);
        setUTotal(d.total);
        setUPage(d.page);
      });
  const loadPolls = (page: number) =>
    api
      .get<Page & { polls: AdminPoll[] }>(`/admin/polls?page=${page}&per_page=${perPage}`)
      .then((d) => {
        setPolls(d.polls);
        setPTotal(d.total);
        setPPage(d.page);
      });

  useEffect(() => {
    if (user?.is_admin) {
      loadUsers(1);
      loadPolls(1);
    }
  }, [user?.is_admin]);

  if (user && !user.is_admin) return <Navigate to="/" replace />;

  const deleteUser = async (u: AdminUser) => {
    if (!confirm(`Delete user "${u.username}" and all their polls, ballots, and sessions?`)) return;
    await api.del(`/admin/users/${u.id}`);
    loadUsers(uPage);
    loadPolls(pPage);
  };
  const deletePoll = async (p: AdminPoll) => {
    if (!confirm(`Delete poll "${p.title}"?`)) return;
    await api.del(`/admin/polls/${p.id}`);
    loadPolls(pPage);
  };

  return (
    <div>
      <h1>Admin</h1>

      <section>
        <h2>Users ({uTotal})</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Created</th>
              <th>Polls</th>
              <th>Admin</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{new Date(u.created_at).toLocaleDateString()}</td>
                <td>{u.poll_count}</td>
                <td>{u.is_admin ? "✓" : ""}</td>
                <td>
                  <button className="link-btn danger" onClick={() => deleteUser(u)}>
                    delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager page={uPage} total={uTotal} perPage={perPage} onChange={loadUsers} />
      </section>

      <section>
        <h2>Polls ({pTotal})</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Creator</th>
              <th>Status</th>
              <th>Ballots</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {polls.map((p) => (
              <tr key={p.id}>
                <td>
                  <a href={`/p/${p.slug}`}>{p.title}</a>
                </td>
                <td>{p.creator}</td>
                <td>
                  <span className={`badge ${p.status}`}>{p.status}</span>
                </td>
                <td>{p.ballot_count}</td>
                <td>
                  <button className="link-btn danger" onClick={() => deletePoll(p)}>
                    delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager page={pPage} total={pTotal} perPage={perPage} onChange={loadPolls} />
      </section>
    </div>
  );
}

function Pager({
  page,
  total,
  perPage,
  onChange,
}: {
  page: number;
  total: number;
  perPage: number;
  onChange: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  if (pages <= 1) return null;
  return (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Prev
      </button>
      <span>
        Page {page} of {pages}
      </span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)}>
        Next →
      </button>
    </div>
  );
}
