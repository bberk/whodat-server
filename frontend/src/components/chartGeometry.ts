/**
 * Pure geometry helpers for the inline SVG VP chart. Kept separate from the component so the
 * scale math and label layout are unit-testable without rendering SVG.
 */

export interface Scale {
  min: number;
  max: number;
  ticks: number[];
}

/** A "nice" axis scale: round step, always spanning zero so the zero line is visible. */
export function niceScale(min: number, max: number, targetTicks = 4): Scale {
  const lo = Math.min(min, 0);
  const hi = Math.max(max, 0);
  if (lo === hi) {
    return { min: -1, max: 1, ticks: [-1, 0, 1] };
  }
  const rawStep = (hi - lo) / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  let step: number;
  if (normalized <= 1) {
    step = 1;
  } else if (normalized <= 2) {
    step = 2;
  } else if (normalized <= 2.5) {
    step = 2.5;
  } else if (normalized <= 5) {
    step = 5;
  } else {
    step = 10;
  }
  step *= magnitude;
  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let tick = niceMin; tick <= niceMax + step / 1e6; tick += step) {
    ticks.push(Number(tick.toFixed(6)));
  }
  return { min: niceMin, max: niceMax, ticks };
}

/**
 * A "nice" axis scale that does not force zero into range. Elo ratings cluster around 1500, so a
 * zero-based axis would flatten every line; this helper rounds only the actual data range.
 */
export function niceValueScale(min: number, max: number, targetTicks = 4): Scale {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, max: 1, ticks: [0, 1] };
  }
  const lo = Math.min(min, max);
  const hi = Math.max(min, max);
  if (lo === hi) {
    return { min: lo - 1, max: hi + 1, ticks: [lo - 1, lo, hi + 1] };
  }
  const rawStep = (hi - lo) / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  let step: number;
  if (normalized <= 1) {
    step = 1;
  } else if (normalized <= 2) {
    step = 2;
  } else if (normalized <= 2.5) {
    step = 2.5;
  } else if (normalized <= 5) {
    step = 5;
  } else {
    step = 10;
  }
  step *= magnitude;
  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let tick = niceMin; tick <= niceMax + step / 1e6; tick += step) {
    ticks.push(Number(tick.toFixed(6)));
  }
  return { min: niceMin, max: niceMax, ticks };
}

/**
 * A "nice" scale whose ticks are whole numbers, for axes that are printed without decimals.
 *
 * Elo ratings cluster tightly, so a 2.5 step would either repeat a rounded label or imply
 * precision the axis does not show. The step therefore never drops below one.
 */
export function niceIntegerScale(min: number, max: number, targetTicks = 4): Scale {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, max: 1, ticks: [0, 1] };
  }
  const lo = Math.min(min, max);
  const hi = Math.max(min, max);
  if (lo === hi) {
    const value = Math.round(lo);
    return { min: value - 1, max: value + 1, ticks: [value - 1, value, value + 1] };
  }
  const rawStep = (hi - lo) / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  let step: number;
  if (normalized <= 1) {
    step = 1;
  } else if (normalized <= 2) {
    step = 2;
  } else if (normalized <= 2.5) {
    step = 3;
  } else if (normalized <= 5) {
    step = 5;
  } else {
    step = 10;
  }
  step = Math.max(1, Math.round(step * magnitude));
  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let tick = niceMin; tick <= niceMax + step / 1e6; tick += step) {
    ticks.push(Number(tick.toFixed(6)));
  }
  return { min: niceMin, max: niceMax, ticks };
}

/** Evenly spaced x position for point `index` of `count`, spanning `length` from `start`. */
export function positionFor(index: number, count: number, start: number, length: number): number {
  if (count <= 1) {
    return start + length / 2;
  }
  return start + (index / (count - 1)) * length;
}

/**
 * Pick the week indexes that get an x-axis tick.
 *
 * The first and last week are always labelled, the rest are spread evenly up to `maxLabels`, and a
 * label closer than `minGap` pixels to its neighbour is dropped. The last week replaces a
 * too-close neighbour so the end of the range stays labelled. Season labels live on their own row,
 * so a season start never forces a second `W1` tick next to the previous season's last week.
 */
export function selectWeekLabelIndices(
  count: number,
  maxLabels: number,
  minGap: number,
  positionOf: (index: number) => number,
): number[] {
  if (count <= 0) {
    return [];
  }
  if (count === 1) {
    return [0];
  }
  const limit = Math.max(2, Math.floor(maxLabels));
  const step = Math.max(1, Math.ceil((count - 1) / (limit - 1)));
  const selected: number[] = [];
  for (let index = 0; index < count - 1; index += step) {
    if (selected.length === 0) {
      selected.push(index);
      continue;
    }
    if (positionOf(index) - positionOf(selected[selected.length - 1]) >= minGap) {
      selected.push(index);
    }
  }
  const last = count - 1;
  if (positionOf(last) - positionOf(selected[selected.length - 1]) >= minGap) {
    selected.push(last);
  } else {
    selected[selected.length - 1] = last;
  }
  return selected;
}

/** Nudge label positions apart so they never overlap, keeping them inside [top, bottom]. */
export function spreadLabelPositions(
  ys: number[],
  minGap: number,
  top: number,
  bottom: number,
): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y || a.index - b.index);
  const placed = order.map(() => 0);
  let previous = top - minGap;
  order.forEach((item, position) => {
    const y = Math.max(item.y, previous + minGap);
    placed[position] = y;
    previous = y;
  });
  const overflow = placed[placed.length - 1] - bottom;
  if (overflow > 0) {
    for (let index = 0; index < placed.length; index += 1) {
      placed[index] -= overflow;
    }
  }
  const result = ys.slice();
  order.forEach((item, position) => {
    result[item.index] = placed[position];
  });
  return result;
}
