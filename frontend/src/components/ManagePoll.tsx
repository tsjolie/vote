import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type PollMeta } from "../api";
import Results from "./Results";

interface QMeta {
  id: string;
  position: number;
  title: string;
  description: string | null;
  is_required: boolean;
  options: { id: string; label: string; position: number }[];
}

interface VoterBallot {
  ballot_id: string;
  user_id: string;
  username: string;
  ranking: string[];
  is_invalidated: boolean;
  is_banned: boolean;
  submitted_at: string;
}
interface VoterQuestion {
  question_id: string;
  position: number;
  title: string;
  options: { id: string; label: string }[];
  ballots: VoterBallot[];
}
interface VotersPayload {
  banned_user_ids: string[];
  questions: VoterQuestion[];
}

type Tab = "manage" | "voters" | "results";

export default function ManagePoll({
  slug,
  poll,
  questions,
  locked,
  reload,
}: {
  slug: string;
  poll: PollMeta;
  questions: QMeta[];
  locked: boolean;
  reload: () => void;
}) {
  const [tab, setTab] = useState<Tab>("manage");
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const open = poll.status === "open";

  const closePoll = async () => {
    if (!confirm("Close this poll permanently? It cannot be reopened.")) return;
    try {
      await api.post(`/polls/${slug}/close`);
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const deletePoll = async () => {
    if (!confirm("Delete this poll and all its votes? This cannot be undone.")) return;
    try {
      await api.del(`/polls/${slug}`);
      nav("/", { replace: true });
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div>
      <div className="row-between">
        <h1>{poll.title}</h1>
        <span className={`badge ${poll.status}`}>{poll.status}</span>
      </div>
      <p className="muted share">
        Share link: <code>{`${location.origin}/p/${slug}`}</code>
      </p>

      <div className="tabs">
        <button className={tab === "manage" ? "active" : ""} onClick={() => setTab("manage")}>
          Manage
        </button>
        <button className={tab === "voters" ? "active" : ""} onClick={() => setTab("voters")}>
          Voters
        </button>
        <button className={tab === "results" ? "active" : ""} onClick={() => setTab("results")}>
          Results
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {tab === "manage" && (
        <div>
          <MetaEditor slug={slug} poll={poll} open={open} reload={reload} />
          {locked && (
            <p className="muted">
              Voting has begun — questions cannot be added or removed, but options can still be
              edited (this invalidates existing ballots on that question).
            </p>
          )}
          {questions.map((q) => (
            <QuestionEditor key={q.id} slug={slug} q={q} open={open} reload={reload} />
          ))}
          <div className="danger-zone">
            {open && (
              <button className="secondary" onClick={closePoll}>
                Close poll
              </button>
            )}
            <button className="danger btn" onClick={deletePoll}>
              Delete poll
            </button>
          </div>
        </div>
      )}

      {tab === "voters" && <VoterTable slug={slug} open={open} />}
      {tab === "results" && <Results slug={slug} />}
    </div>
  );
}

function MetaEditor({
  slug,
  poll,
  open,
  reload,
}: {
  slug: string;
  poll: PollMeta;
  open: boolean;
  reload: () => void;
}) {
  const [title, setTitle] = useState(poll.title);
  const [closesAt, setClosesAt] = useState(
    poll.closes_at ? toLocalInput(poll.closes_at) : "",
  );
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    try {
      await api.put(`/polls/${slug}/meta`, {
        title,
        closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        clear_closes_at: !closesAt,
      });
      setMsg("Saved.");
      reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  if (!open) return null;
  return (
    <fieldset>
      <legend>Poll details</legend>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
      </label>
      <label>
        Closes at (local time; leave blank for no deadline)
        <input
          type="datetime-local"
          value={closesAt}
          onChange={(e) => setClosesAt(e.target.value)}
        />
      </label>
      {msg && <p className="muted">{msg}</p>}
      <button className="secondary" onClick={save}>
        Save details
      </button>
    </fieldset>
  );
}

function QuestionEditor({
  slug,
  q,
  open,
  reload,
}: {
  slug: string;
  q: QMeta;
  open: boolean;
  reload: () => void;
}) {
  const [title, setTitle] = useState(q.title);
  const [description, setDescription] = useState(q.description ?? "");
  const [required, setRequired] = useState(q.is_required);
  const [labels, setLabels] = useState(q.options.map((o) => o.label));
  const [msg, setMsg] = useState<string | null>(null);

  const optionsChanged =
    labels.length !== q.options.length ||
    labels.some((l, i) => l !== q.options[i]?.label);
  const titleChanged = title !== q.title;
  const invalidating = optionsChanged || titleChanged;

  const saveFree = async () => {
    // description / required only — never invalidates.
    try {
      await api.put(`/polls/${slug}/questions/${q.id}`, {
        description,
        is_required: required,
      });
      setMsg("Saved.");
      reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const saveInvalidating = async () => {
    const impact = await api.get<{ ballots_to_invalidate: number }>(
      `/polls/${slug}/questions/${q.id}/impact`,
    );
    const n = impact.ballots_to_invalidate;
    const proceed = confirm(
      n > 0
        ? `This change will invalidate ${n} ballot${n === 1 ? "" : "s"} on this question. ` +
            `Affected voters must re-vote. Continue?`
        : "Save this change?",
    );
    if (!proceed) return;
    try {
      await api.put(`/polls/${slug}/questions/${q.id}`, {
        title,
        options: labels.map((label) => ({ label })),
      });
      setMsg("Saved.");
      reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  return (
    <fieldset className="question-editor">
      <legend>Question {q.position + 1}</legend>
      <label>
        Title {titleChanged && <span className="warn-inline">(changing invalidates ballots)</span>}
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!open} />
      </label>
      <label>
        Description (freely editable)
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={!open}
        />
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={required}
          onChange={(e) => setRequired(e.target.checked)}
          disabled={!open}
        />
        Required
      </label>

      <div className="options-editor">
        <span>
          Options{" "}
          {optionsChanged && <span className="warn-inline">(changing invalidates ballots)</span>}
        </span>
        {labels.map((l, i) => (
          <div key={i} className="opt-row">
            <input
              value={l}
              disabled={!open}
              onChange={(e) => {
                const next = [...labels];
                next[i] = e.target.value;
                setLabels(next);
              }}
            />
            {open && labels.length > 2 && (
              <button
                className="link-btn danger"
                onClick={() => setLabels(labels.filter((_, idx) => idx !== i))}
              >
                ×
              </button>
            )}
          </div>
        ))}
        {open && labels.length < 10 && (
          <button className="link-btn" onClick={() => setLabels([...labels, ""])}>
            + add option
          </button>
        )}
      </div>

      {msg && <p className="muted">{msg}</p>}
      {open && (
        <div className="btn-group">
          <button className="secondary" onClick={saveFree}>
            Save description / required
          </button>
          {invalidating && (
            <button className="danger btn" onClick={saveInvalidating}>
              Save title/options (invalidates ballots)
            </button>
          )}
        </div>
      )}
    </fieldset>
  );
}

function VoterTable({ slug, open }: { slug: string; open: boolean }) {
  const [data, setData] = useState<VotersPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .get<VotersPayload>(`/polls/${slug}/voters`)
      .then(setData)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, [slug]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const banned = new Set(data.banned_user_ids);

  const invalidate = async (ballotId: string) => {
    if (!confirm("Invalidate this ballot? The voter may re-vote.")) return;
    await api.post(`/polls/${slug}/ballots/${ballotId}/invalidate`);
    load();
  };
  const ban = async (userId: string) => {
    if (!confirm("Ban this user from the poll? Their ballots stop counting.")) return;
    await api.post(`/polls/${slug}/bans`, { user_id: userId });
    load();
  };
  const unban = async (userId: string) => {
    await api.del(`/polls/${slug}/bans/${userId}`);
    load();
  };

  return (
    <div>
      {data.questions.map((q) => {
        const labelFor = (id: string) =>
          q.options.find((o) => o.id === id)?.label ?? id;
        return (
          <div key={q.question_id} className="card">
            <h3>
              Q{q.position + 1}. {q.title}
            </h3>
            {q.ballots.length === 0 ? (
              <p className="muted">No ballots.</p>
            ) : (
              <table className="voter-table">
                <thead>
                  <tr>
                    <th>Voter</th>
                    <th>Ranking</th>
                    <th>Submitted</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {q.ballots.map((b) => (
                    <tr key={b.ballot_id} className={b.is_invalidated || banned.has(b.user_id) ? "dim" : ""}>
                      <td>{b.username}</td>
                      <td>{b.ranking.map(labelFor).join(" › ")}</td>
                      <td>{new Date(b.submitted_at).toLocaleString()}</td>
                      <td>
                        {banned.has(b.user_id)
                          ? "banned"
                          : b.is_invalidated
                            ? "invalidated"
                            : "counted"}
                      </td>
                      <td className="actions">
                        {open && !b.is_invalidated && !banned.has(b.user_id) && (
                          <button className="link-btn" onClick={() => invalidate(b.ballot_id)}>
                            invalidate
                          </button>
                        )}
                        {banned.has(b.user_id) ? (
                          <button className="link-btn" onClick={() => unban(b.user_id)}>
                            un-ban
                          </button>
                        ) : (
                          <button className="link-btn danger" onClick={() => ban(b.user_id)}>
                            ban
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </div>
  );
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const off = d.getTimezoneOffset();
  const local = new Date(d.getTime() - off * 60000);
  return local.toISOString().slice(0, 16);
}
