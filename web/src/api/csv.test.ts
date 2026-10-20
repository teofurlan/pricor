import { describe, expect, it } from "vitest";
import { parseCsv } from "./csv";

describe("parseCsv", () => {
  it("reads RFC 4180 quoting, escaped quotes, embedded separators and CRLF line ends", () => {
    const text = 'code,description\r\nA1,"Bolt, 6 mm"\r\nB2,"Nut ""M6"""\r\n';
    expect(parseCsv(text)).toEqual([["code", "description"], ["A1", "Bolt, 6 mm"], ["B2", 'Nut "M6"']]);
  });

  it("keeps empty cells and line breaks inside quotes, and ignores a leading BOM", () => {
    expect(parseCsv('﻿a,b,c\n1,,"x\ny"\n')).toEqual([["a", "b", "c"], ["1", "", "x\ny"]]);
  });
});
