/* Copyright 2024 Marimo. All rights reserved. */
import React, { Suspense } from "react";
import { createBatchedLoader } from "@/plugins/impl/vega/batched";
import { useTheme } from "@/theme/useTheme";
import { logNever } from "@/utils/assertNever";
import { prettyDate } from "@/utils/dates";
import { prettyNumber, prettyScientificNumber } from "@/utils/numbers";
import { DelayMount } from "../../utils/delay-mount";
import { DatePopover } from "../date-popover";
import { ChartSkeleton } from "./chart-skeleton";
import { ColumnChartSpecModel } from "./chart-spec-model";

export const ColumnChartContext = React.createContext<
  ColumnChartSpecModel<unknown>
>(ColumnChartSpecModel.EMPTY);

interface Props<TData, TValue> {
  columnId: string;
}

const LazyVegaLite = React.lazy(() =>
  import("react-vega").then((m) => ({ default: m.VegaLite })),
);

// We batch multiple calls to the same URL returning the same promise
// for all calls with the same key.
const batchedLoader = createBatchedLoader();

export const TableColumnSummary = <TData, TValue>({
  columnId,
}: Props<TData, TValue>) => {
  const chartSpecModel = React.use(ColumnChartContext);
  const { theme } = useTheme();
  const { spec, type, stats } = chartSpecModel.getHeaderSummary(columnId);
  let chart: React.ReactNode = null;
  if (spec) {
    const skeleton = <ChartSkeleton seed={columnId} width={80} height={40} />;
    chart = (
      <DelayMount
        milliseconds={200}
        visibility={true}
        rootMargin="200px"
        fallback={skeleton}
      >
        <Suspense fallback={skeleton}>
          <LazyVegaLite
            spec={spec}
            width={70}
            height={30}
            renderer="svg"
            // @ts-expect-error - Our `loader.load` method is broader than VegaLite's typings but is functionally supported.
            loader={batchedLoader}
            style={{ minWidth: "unset", maxHeight: "40px" }}
            actions={false}
            theme={theme === "dark" ? "dark" : "vox"}
          />
        </Suspense>
      </DelayMount>
    );
  }

  const renderDate = (
    date: string | number | null | undefined,
    type: "date" | "datetime",
  ) => {
    return (
      <DatePopover date={date} type={type}>
        {prettyDate(date, type)}
      </DatePopover>
    );
  };

  const renderStats = () => {
    if (!stats) {
      return null;
    }

    switch (type) {
      case "date":
      case "datetime":
        // Without a chart
        if (!spec) {
          return (
            <div className="flex flex-col whitespace-pre">
              <span>min: {renderDate(stats.min, type)}</span>
              <span>max: {renderDate(stats.max, type)}</span>
              <span>unique: {prettyNumber(stats.unique)}</span>
            </div>
          );
        }

        return (
          <div className="flex justify-between w-full px-2 whitespace-pre">
            <span>{renderDate(stats.min, type)}</span>
            {stats.min === stats.max ? null : (
              <span>-{renderDate(stats.max, type)}</span>
            )}
          </div>
        );
      case "integer":
      case "number":
        // Without a chart
        if (!spec) {
          return (
            <div className="flex flex-col whitespace-pre">
              <span>
                min:{" "}
                {typeof stats.min === "number"
                  ? prettyScientificNumber(stats.min, { shouldRound: true })
                  : stats.min}
              </span>
              <span>
                max:{" "}
                {typeof stats.max === "number"
                  ? prettyScientificNumber(stats.max, { shouldRound: true })
                  : stats.max}
              </span>
              <span>unique: {prettyNumber(stats.unique)}</span>
            </div>
          );
        }

        // Numerical bar charts use built-in vega axis and ticks
        return null;
      case "boolean":
        // Without a chart
        if (!spec) {
          return (
            <div className="flex flex-col whitespace-pre">
              <span>true: {prettyNumber(stats.true)}</span>
              <span>false: {prettyNumber(stats.false)}</span>
            </div>
          );
        }

        return null;
      case "time":
        return null;
      case "string":
        if (!spec) {
          return (
            <div className="flex flex-col whitespace-pre">
              <span>unique: {prettyNumber(stats.unique)}</span>
            </div>
          );
        }
        return null;
      case "unknown":
        return (
          <div className="flex flex-col whitespace-pre">
            <span>nulls: {prettyNumber(stats.nulls)}</span>
          </div>
        );
      default:
        logNever(type);
        return null;
    }
  };

  return (
    <div className="flex flex-col items-center text-xs text-muted-foreground align-end">
      {chart}
      {renderStats()}
    </div>
  );
};
