import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartMarker } from "./ChartMarker";

describe("ChartMarker", () => {
  it("renders circle marker", () => {
    const { container } = render(
      <svg>
        <ChartMarker shape="circle" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    const circle = container.querySelector("circle");
    expect(circle).toBeInTheDocument();
    expect(circle).toHaveAttribute("cx", "10");
    expect(circle).toHaveAttribute("cy", "20");
    expect(circle).toHaveAttribute("r", "4");
  });

  it("renders square marker", () => {
    const { container } = render(
      <svg>
        <ChartMarker shape="square" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    const rect = container.querySelector("rect");
    expect(rect).toBeInTheDocument();
    expect(rect).toHaveAttribute("x", "6");
    expect(rect).toHaveAttribute("y", "16");
    expect(rect).toHaveAttribute("width", "8");
    expect(rect).toHaveAttribute("height", "8");
  });

  it("renders triangle, diamond, plus, and cross markers", () => {
    const { container: tContainer } = render(
      <svg>
        <ChartMarker shape="triangle" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    expect(tContainer.querySelector("path")).toBeInTheDocument();

    const { container: dContainer } = render(
      <svg>
        <ChartMarker shape="diamond" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    expect(dContainer.querySelector("path")).toBeInTheDocument();

    const { container: pContainer } = render(
      <svg>
        <ChartMarker shape="plus" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    expect(pContainer.querySelector("path")).toBeInTheDocument();

    const { container: cContainer } = render(
      <svg>
        <ChartMarker shape="cross" x={10} y={20} color="#ff0000" size={4} />
      </svg>,
    );
    expect(cContainer.querySelector("path")).toBeInTheDocument();
  });
});
