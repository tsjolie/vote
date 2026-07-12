import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

interface DraftQuestion {
  title: string;
  description: string;
  is_required: boolean;
  options: string[];
}

type Step = "meta" | "questions" | "review";

export default function CreatePoll() {
  const nav = useNavigate();
  const [step, setStep] = useState<Step>("meta");
  const [title, setTitle] = useState("");
  const [closesAt, setClosesAt] = useState(""); // datetime-local (creator's local tz)
  const [questions, setQuestions] = useState<DraftQuestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // in-progress question being built
  const [qTitle, setQTitle] = useState("");
  const [qDesc, setQDesc] = useState("");
  const [qRequired, setQRequired] = useState(true);
  const [qOptions, setQOptions] = useState<string[]>(["", ""]);

  const resetQuestion = () => {
    setQTitle("");
    setQDesc("");
    setQRequired(true);
    setQOptions(["", ""]);
  };

  const addQuestion = () => {
    setError(null);
    const opts = qOptions.map((o) => o.trim()).filter(Boolean);
    if (!qTitle.trim()) return setError("Question needs a title.");
    if (opts.length < 2 || opts.length > 10)
      return setError("Each question needs 2–10 options.");
    if (questions.length >= 20) return setError("A poll can have at most 20 questions.");
    setQuestions([
      ...questions,
      { title: qTitle.trim(), description: qDesc.trim(), is_required: qRequired, options: opts },
    ]);
    resetQuestion();
  };

  const removeQuestion = (i: number) =>
    setQuestions(questions.filter((_, idx) => idx !== i));

  const publish = async () => {
    setError(null);
    if (!title.trim()) return setError("Poll needs a title.");
    if (questions.length < 1) return setError("Add at least one question.");
    setBusy(true);
    try {
      const payload = {
        title: title.trim(),
        closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        questions: questions.map((q) => ({
          title: q.title,
          description: q.description || null,
          is_required: q.is_required,
          options: q.options.map((label) => ({ label })),
        })),
      };
      const res = await api.post<{ slug: string }>("/polls", payload);
      nav(`/p/${res.slug}`, { replace: true });
    } catch (err: any) {
      setError(err.message || "Could not create poll.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h1>Create a poll</h1>
      <div className="steps">
        <span className={step === "meta" ? "active" : ""}>1. Details</span>
        <span className={step === "questions" ? "active" : ""}>2. Questions</span>
        <span className={step === "review" ? "active" : ""}>3. Review</span>
      </div>

      {error && <p className="error">{error}</p>}

      {step === "meta" && (
        <div>
          <label>
            Poll title
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          </label>
          <label>
            End date/time (optional, your local time)
            <input
              type="datetime-local"
              value={closesAt}
              onChange={(e) => setClosesAt(e.target.value)}
            />
          </label>
          <button
            className="primary"
            onClick={() => {
              if (!title.trim()) return setError("Poll needs a title.");
              setError(null);
              setStep("questions");
            }}
          >
            Next: add questions
          </button>
        </div>
      )}

      {step === "questions" && (
        <div>
          {questions.length > 0 && (
            <ol className="draft-list">
              {questions.map((q, i) => (
                <li key={i}>
                  <strong>{q.title}</strong> {q.is_required ? "" : "(optional)"} —{" "}
                  {q.options.length} options
                  <button className="link-btn danger" onClick={() => removeQuestion(i)}>
                    remove
                  </button>
                </li>
              ))}
            </ol>
          )}

          <fieldset>
            <legend>Add question {questions.length + 1}</legend>
            <label>
              Title
              <input value={qTitle} onChange={(e) => setQTitle(e.target.value)} maxLength={300} />
            </label>
            <label>
              Description (optional)
              <textarea
                value={qDesc}
                onChange={(e) => setQDesc(e.target.value)}
                maxLength={2000}
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={qRequired}
                onChange={(e) => setQRequired(e.target.checked)}
              />
              Required (voters cannot skip)
            </label>
            <div className="options-editor">
              <span>Options (2–10):</span>
              {qOptions.map((o, i) => (
                <div key={i} className="opt-row">
                  <input
                    value={o}
                    maxLength={200}
                    placeholder={`Option ${i + 1}`}
                    onChange={(e) => {
                      const next = [...qOptions];
                      next[i] = e.target.value;
                      setQOptions(next);
                    }}
                  />
                  {qOptions.length > 2 && (
                    <button
                      className="link-btn danger"
                      onClick={() => setQOptions(qOptions.filter((_, idx) => idx !== i))}
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
              {qOptions.length < 10 && (
                <button className="link-btn" onClick={() => setQOptions([...qOptions, ""])}>
                  + add option
                </button>
              )}
            </div>
            <button className="secondary" onClick={addQuestion}>
              Add question
            </button>
          </fieldset>

          <div className="row-between">
            <button className="link-btn" onClick={() => setStep("meta")}>
              ← Back
            </button>
            <button
              className="primary"
              disabled={questions.length < 1}
              onClick={() => setStep("review")}
            >
              Review →
            </button>
          </div>
        </div>
      )}

      {step === "review" && (
        <div>
          <h2>{title}</h2>
          {closesAt && <p className="muted">Closes: {new Date(closesAt).toLocaleString()}</p>}
          <ol className="draft-list">
            {questions.map((q, i) => (
              <li key={i}>
                <strong>{q.title}</strong> {q.is_required ? "" : "(optional)"}
                {q.description && <p className="muted">{q.description}</p>}
                <ul>
                  {q.options.map((o, j) => (
                    <li key={j}>{o}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          <div className="row-between">
            <button className="link-btn" onClick={() => setStep("questions")}>
              ← Back
            </button>
            <button className="primary" disabled={busy} onClick={publish}>
              {busy ? "Publishing…" : "Publish poll"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
