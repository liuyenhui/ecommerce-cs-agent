export type SelectionNodeView = {
  id: string;
  stroke: string;
};

export type SelectionCell = {
  attr: (path: string, value: unknown) => void;
};

export function applySelectedNodeStyles(
  views: SelectionNodeView[],
  selectedNodeId: string,
  getCell: (id: string) => SelectionCell | null | undefined
) {
  views.forEach((view) => {
    const cell = getCell(view.id);
    if (!cell) return;
    cell.attr("body/stroke", view.id === selectedNodeId ? "#0f172a" : view.stroke);
    cell.attr("body/strokeWidth", view.id === selectedNodeId ? 3 : 2);
  });
}
