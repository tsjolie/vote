import { useEffect, useState } from "react";
import { api, type OptionOut } from "../api";
import SortableBallot from "./SortableBallot";

interface QMeta {
  id: string;
  position: number;
  title: string;
  description: string | null;
  is_required: boolean;
  my_status: "none" | "answered" | "invalidated";
}

interface VoteView {
  question: {
    id: string;
    title: string;
    description: string | null;
    is_required: boolean;
    option_count: number;
  };
  order: OptionOut[];
  my_status: string;
}

export default function VotingFlow({
  slug,
  questions,
  startIndex,
  onDone,
}: {
  slug: string;
  questions: QMeta[];
  startIndex: number;
  onDone: () => void;
}) {
  const [index, setIndex] = useState(startIndex);
  const [view, setView] = useState<VoteView | null>(null);
  const [order, setOrder] = useState<OptionOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const q = questions[index];

  useEffect(() => {
    if (!q) {
      onDone();
      return;
    }
    setError(null);
    setView(null);
    api
      .get<VoteView>(`/polls/${slug}/questions/${q.id}/vote`)
      .then((v) => {
        setView(v);
        setOrder(v.order);
      })
      .catch((e) => setError(e.message));
  }, [index, q?.id, slug]);

  if (!q) return null;

  const advance = () => {
    if (index + 1 >= questions.length) onDone();
    else setIndex(index + 1);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/polls/${slug}/questions/${q.id}/ballot`, {
        ranking: order.map((o) => o.id),
      });
      advance();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/polls/${slug}/questions/${q.id}/skip`);
      advance();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <p className="progress">
        Question {index + 1} of {questions.length}
      </p>
      <h2>{q.title}</h2>
      {q.description && <p className="muted">{q.description}</p>}
      {q.my_status === "invalidated" && (
        <p className="warn">
          Your previous vote on this question was invalidated. Please re-rank.
        </p>
      )}
      <p className="hint">Drag to rank from most (top) to least preferred.</p>

      {error && <p className="error">{error}</p>}

      {view ? (
        <>
          <SortableBallot options={order} onChange={setOrder} />
          <div className="row-between vote-actions">
            <div>
              {index > 0 && (
                <button className="link-btn" onClick={() => setIndex(index - 1)}>
                  ← Previous
                </button>
              )}
            </div>
            <div className="btn-group">
              {!q.is_required && (
                <button className="secondary" disabled={busy} onClick={skip}>
                  Skip this question
                </button>
              )}
              <button className="primary" disabled={busy} onClick={submit}>
                {busy ? "…" : index + 1 >= questions.length ? "Submit & see results" : "Submit & next"}
              </button>
            </div>
          </div>
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </div>
  );
}
