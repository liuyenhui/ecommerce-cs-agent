export type GraphUiState = {
  unavailable: boolean;
  retryKey: number;
};

export type GraphUiEvent = {
  type: "failed" | "available" | "retry" | "reset";
};

export function reduceGraphUiState(state: GraphUiState, event: GraphUiEvent): GraphUiState {
  if (event.type === "failed") return { ...state, unavailable: true };
  if (event.type === "retry") return { unavailable: false, retryKey: state.retryKey + 1 };
  if (event.type === "reset") return { unavailable: false, retryKey: 0 };
  return { ...state, unavailable: false };
}
