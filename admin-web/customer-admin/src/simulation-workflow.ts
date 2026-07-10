type SimulationTrace = {
  decision_id?: unknown;
  customer_message?: unknown;
};

export type OperationToken = {
  storeId: string;
  generation: number;
  requestId: number;
};

export function isCurrentOperation(
  operation: OperationToken,
  currentStoreId: string,
  currentGeneration: number,
  currentRequestId: number,
  mounted = true
) {
  return mounted
    && operation.storeId === currentStoreId
    && operation.generation === currentGeneration
    && operation.requestId === currentRequestId;
}

export function buildCanonicalSimulationTrace<T extends SimulationTrace>(trace: T, submittedContent: string): T {
  if (String(trace.customer_message || "").trim()) return trace;
  return { ...trace, customer_message: submittedContent };
}

export async function requireReloadedSimulation<T extends SimulationTrace>(
  reload: () => Promise<T[]>,
  decisionId: string
): Promise<T> {
  if (!decisionId.trim()) {
    throw new Error("模拟结果缺少决策编号，输入内容已保留。");
  }
  let rows: T[];
  try {
    rows = await reload();
  } catch {
    throw new Error("模拟已创建，但会话历史刷新失败，请点击刷新后再查看。输入内容已保留。");
  }

  const createdTrace = rows.find((trace) => String(trace.decision_id || "") === decisionId);
  if (!createdTrace) {
    throw new Error("模拟已创建，但刷新结果中未找到新会话，请点击刷新后再查看。输入内容已保留。");
  }
  return createdTrace;
}
