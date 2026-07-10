import React from "react";
import { Bot, Loader2 } from "lucide-react";

export type SimulationComposerProps = {
  value: string;
  loading: boolean;
  error: string | null;
  emptyState?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
};

export function SimulationComposer({
  value,
  loading,
  error,
  emptyState = false,
  onChange,
  onSubmit
}: SimulationComposerProps) {
  const [validationError, setValidationError] = React.useState("");
  const visibleError = validationError || error;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!value.trim()) {
      setValidationError("请输入模拟客户问题");
      return;
    }
    if (loading) return;
    setValidationError("");
    onSubmit();
  }

  function change(nextValue: string) {
    if (nextValue.trim()) setValidationError("");
    onChange(nextValue);
  }

  return (
    <form className={`messageSimulator composerSimulator ${emptyState ? "emptyComposer" : ""}`} onSubmit={submit}>
      {emptyState ? (
        <div className="simulationEmptyIntro">
          <strong>还没有会话，先模拟一次客户咨询</strong>
          <p>模拟咨询不会发送给真实买家</p>
        </div>
      ) : null}
      <label>
        模拟客户咨询
        <textarea
          value={value}
          onChange={(event) => change(event.target.value)}
          placeholder="例如：这款商品有哪些尺寸，什么时候可以发货？"
          aria-describedby={visibleError ? "simulation-composer-error" : undefined}
        />
      </label>
      {visibleError ? <p id="simulation-composer-error" className="simulationError" role="alert">{visibleError}</p> : null}
      <div className="buttonRow end">
        <button className="primaryButton" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <Bot size={16} />}
          模拟决策
        </button>
      </div>
    </form>
  );
}
