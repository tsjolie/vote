import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type PollMeta } from "../api";
import ManagePoll from "../components/ManagePoll";
import Results from "../components/Results";
import VotingFlow from "../components/VotingFlow";

interface QView {
  id: string;
  position: number;
  title: string;
  description: string | null;
  is_required: boolean;
  options: { id: string; label: string; position: number }[];
  my_status: "none" | "answered" | "invalidated";
}

interface PollPayload {
  poll: PollMeta;
  viewer_role:
    | "creator"
    | "voter"
    | "voter_incomplete"
    | "non_voter"
    | "banned";
  is_creator?: boolean;
  questions?: QView[];
  my_counted_ballots?: number;
  questions_locked?: boolean;
}

export default function PollView() {
  const { slug } = useParams<{ slug: string }>();
  const [data, setData] = useState<PollPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [voting, setVoting] = useState(false);

  const load = useCallback(() => {
    if (!slug) return;
    api
      .get<PollPayload>(`/polls/${slug}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setError("Poll not found.");
        else setError(e.message);
      });
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <p className="error">{error}</p>;
  if (!data || !slug) return <p className="muted">Loading…</p>;

  if (data.viewer_role === "banned") {
    return (
      <div className="card center">
        <h1>You cannot participate in this poll.</h1>
        <p className="muted">The poll creator has banned you from this poll.</p>
      </div>
    );
  }

  if (data.viewer_role === "creator") {
    return (
      <ManagePoll
        slug={slug}
        poll={data.poll}
        questions={data.questions ?? []}
        locked={!!data.questions_locked}
        reload={load}
      />
    );
  }

  const questions = data.questions ?? [];
  const firstUnanswered = questions.findIndex((q) => q.my_status !== "answered");
  const needsVoting =
    data.poll.status === "open" &&
    questions.some((q) => q.is_required && q.my_status !== "answered");

  // Explicit voting session (resume / change votes) or forced when required work remains.
  if ((voting || needsVoting) && data.poll.status === "open" && questions.length > 0) {
    const start = firstUnanswered >= 0 ? firstUnanswered : 0;
    return (
      <VotingFlow
        slug={slug}
        questions={questions}
        startIndex={start}
        onDone={() => {
          setVoting(false);
          load();
        }}
      />
    );
  }

  // Otherwise: has counted ballots (or poll closed) -> results.
  const canSeeResults = (data.my_counted_ballots ?? 0) > 0;
  return (
    <div>
      {data.poll.status === "open" && questions.length > 0 && (
        <div className="row-between">
          <span className="muted">You've voted in this poll.</span>
          <button className="secondary" onClick={() => setVoting(true)}>
            Revisit / change my votes
          </button>
        </div>
      )}
      {canSeeResults ? (
        <Results slug={slug} />
      ) : (
        <div className="card">
          <h1>{data.poll.title}</h1>
          <p className="muted">
            This poll is closed and you have no counted ballots, so there are no results to
            show you.
          </p>
        </div>
      )}
    </div>
  );
}
