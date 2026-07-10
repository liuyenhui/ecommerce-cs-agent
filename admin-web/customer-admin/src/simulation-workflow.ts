type SimulationTrace = {
  decision_id?: unknown;
};

export async function requireReloadedSimulation<T extends SimulationTrace>(
  reload: Promise<T[]>,
  decisionId: string
): Promise<T> {
  let rows: T[];
  try {
    rows = await reload;
  } catch {
    throw new Error("模拟已创建，但会话历史刷新失败，请点击刷新后再查看。输入内容已保留。");
  }

  const createdTrace = rows.find((trace) => String(trace.decision_id || "") === decisionId);
  if (!createdTrace) {
    throw new Error("模拟已创建，但刷新结果中未找到新会话，请点击刷新后再查看。输入内容已保留。");
  }
  return createdTrace;
}
