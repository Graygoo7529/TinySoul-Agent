/**
 * JSON-safe dynamic values, mirroring the JsonValue/JsonObject defs shared by
 * the exported schemas in docs/endpoint/contracts/schemas/. Owner content
 * stays in these types at the HTTP boundary and is narrowed by the decoder
 * that actually consumes it.
 */

export type JsonScalar = string | number | boolean | null;

export type JsonValue = JsonScalar | JsonValue[] | JsonObject;

export interface JsonObject {
  [key: string]: JsonValue;
}
