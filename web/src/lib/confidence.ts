export type ConfidenceLevel = "high" | "medium" | "low";

/** A score in plain words; the number itself means little to a shopkeeper. */
export function confidenceLevel(score: number): ConfidenceLevel {
  return score >= 0.8 ? "high" : score >= 0.5 ? "medium" : "low";
}
