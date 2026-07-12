import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type OptionOut, type Tally } from "../api";

interface QResult {
  question_id: string;
  position: number;
  title: string;
  description: string | null;
  options: OptionOut[];
  tally: Tally;
}
interface ResultsPayload {
  poll: { id: string; slug: string; title: string; status: string };
  is_creator: boolean;
  questions: QResult[];
}

const TB_LABEL: Record<string, string> = {
  borda: "Borda count",
  first_choice: "round-1 first choices",
  random: "deterministic random",
};

function QuestionResult({ q }: { q: QResult }) {
  const [expanded, setExpanded] = useState(false);
  const labels: Record<string, string> = {};
  q.options.forEach((o) => (labels[o.id] = o.label));

  const rounds = q.tally.rounds;
  const firstRound = rounds[0]?.counts ?? {};
  const finalRound = rounds[rounds.length - 1]?.counts ?? {};

  // Headline: first-round vs final-round votes per option.
  const headline = q.options.map((o) => ({
    name: o.label,
    id: o.id,
    first: firstRound[o.id] ?? 0,
    final: finalRound[o.id] ?? 0,
    eliminatedEarly: !(o.id in finalRound),
    winner: q.tally.winner_option_id === o.id,
  }));

  const winnerLabel = q.tally.winner_option_id
    ? labels[q.tally.winner_option_id]
    : null;

  return (
    <div className="card result-card">
      <h3>{q.title}</h3>
      {q.description && <p className="muted">{q.description}</p>}
      <p className="muted">
        {q.tally.total_ballots} counted ballot{q.tally.total_ballots === 1 ? "" : "s"}
        {winnerLabel && (
          <>
            {" · "}
            <strong className="winner">Winner: {winnerLabel} 🏆</strong>
          </>
        )}
      </p>

      {q.tally.total_ballots === 0 ? (
        <p className="muted">No counted ballots yet.</p>
      ) : (
        <>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={Math.max(180, headline.length * 44)}>
              <BarChart data={headline} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={110} />
                <Tooltip />
                <Legend />
                <Bar dataKey="first" name="First round" fill="#6b8cff" />
                <Bar dataKey="final" name="Final round">
                  {headline.map((d) => (
                    <Cell
                      key={d.id}
                      fill={d.winner ? "#2fae66" : d.eliminatedEarly ? "#d0d0d0" : "#3a63d0"}
                      fillOpacity={d.eliminatedEarly ? 0.5 : 1}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <button className="link-btn" onClick={() => setExpanded((e) => !e)}>
            {expanded ? "Hide" : "Show"} round-by-round breakdown ({rounds.length} round
            {rounds.length === 1 ? "" : "s"})
          </button>

          {expanded && (
            <div className="rounds">
              {rounds.map((r) => {
                const data = Object.entries(r.counts).map(([id, count]) => ({
                  name: labels[id] ?? id,
                  count,
                  eliminated: r.eliminated === id,
                }));
                return (
                  <div key={r.round} className="round">
                    <h4>Round {r.round}</h4>
                    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 34)}>
                      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
                        <XAxis type="number" allowDecimals={false} />
                        <YAxis type="category" dataKey="name" width={110} />
                        <Tooltip />
                        <Bar dataKey="count">
                          {data.map((d, i) => (
                            <Cell key={i} fill={d.eliminated ? "#e06666" : "#6b8cff"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    {r.eliminated ? (
                      <p className="muted">
                        Eliminated: <strong>{labels[r.eliminated] ?? r.eliminated}</strong>
                        {r.tiebreak_used && (
                          <> — tiebreak via {TB_LABEL[r.tiebreak_used]}</>
                        )}
                      </p>
                    ) : (
                      <p className="muted">Majority reached — winner decided.</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Results({ slug }: { slug: string }) {
  const [data, setData] = useState<ResultsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      api
        .get<ResultsPayload>(`/polls/${slug}/results`)
        .then((d) => active && setData(d))
        .catch((e) => active && setError(e.message));
    load();
    // Live updates: poll every 10 seconds (§9).
    const t = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [slug]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading results…</p>;

  return (
    <div>
      <h1>{data.poll.title}</h1>
      <p className="muted">
        Live results · <span className={`badge ${data.poll.status}`}>{data.poll.status}</span>
      </p>
      {data.questions.map((q) => (
        <QuestionResult key={q.question_id} q={q} />
      ))}
    </div>
  );
}
