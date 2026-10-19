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

/** Evenly spaced x position for point `index` of `count`, spanning `length` from `start`. */
export function positionFor(index: number, count: number, start: number, length: number): number {
  if (count <= 1) {
    return start + length / 2;
  }
  return start + (index / (count - 1)) * length;
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
