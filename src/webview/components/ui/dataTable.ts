export interface Column<R> {
  key: string;
  label: string;
  numeric?: boolean;
  /** `fn` (ellipsis), `loc` (muted path, ellipsis from the left) or `msg` (wraps) */
  cellClass?: 'fn' | 'loc' | 'msg';
  title?: string;
  /** sort value (and the bar length for `bar` columns) */
  value: (row: R) => number | string;
  /** cell text when the column has no `cell-<key>` slot; defaults to the value */
  text?: (row: R) => string;
  /** draw a proportional bar behind the cell */
  bar?: boolean;
}
