import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

interface MinePoll {
  id: string;
  slug: string;
  title: string;
  status: string;
  closes_at: string | null;
  vote_count: number;
}
interface VotedPoll {
  id: string;
  slug: string;
  title: string;
  status: string;
}

export default function Dashboard() {
  const [mine, setMine] = useState<MinePoll[]>([]);
  const [voted, setVoted] = useState<VotedPoll[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<MinePoll[]>("/polls/mine"),
      api.get<VotedPoll[]>("/polls/voted"),
    ])
      .then(([m, v]) => {
        setMine(m);
        setVoted(v);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="muted">Loading…</div>;

  return (
    <div>
      <div className="row-between">
        <h1>Your polls</h1>
        <Link to="/create" className="primary btn">
          + Create poll
        </Link>
      </div>

      <section>
        <h2>Polls you created</h2>
        {mine.length === 0 ? (
          <p className="muted">No polls yet.</p>
        ) : (
          <ul className="poll-list">
            {mine.map((p) => (
              <li key={p.id}>
                <Link to={`/p/${p.slug}`}>{p.title}</Link>
                <span className={`badge ${p.status}`}>{p.status}</span>
                <span className="muted">{p.vote_count} counted ballots</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>Polls you've voted in</h2>
        {voted.length === 0 ? (
          <p className="muted">You haven't voted in any polls yet.</p>
        ) : (
          <ul className="poll-list">
            {voted.map((p) => (
              <li key={p.id}>
                <Link to={`/p/${p.slug}`}>{p.title}</Link>
                <span className={`badge ${p.status}`}>{p.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
