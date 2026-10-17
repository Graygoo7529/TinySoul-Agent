import type { InterfaceSettings, PresentationAssets, PresentationConfig } from "../presentation";
import type { RequestOptions, V2Transport } from "../transport";

export class PresentationClient {
  constructor(private readonly transport: V2Transport) {}

  configuration(options?: RequestOptions): Promise<PresentationConfig> {
    return this.transport.get("/presentation/configs/interface", options);
  }

  saveConfiguration(changes: Partial<InterfaceSettings>, options?: RequestOptions): Promise<PresentationConfig> {
    return this.transport.patch("/presentation/configs/interface", { ...options, body: { changes } });
  }

  assets(options?: RequestOptions): Promise<PresentationAssets> {
    return this.transport.get("/presentation/assets", options);
  }

  readBlob(path: string, options?: RequestOptions): Promise<Response> {
    return this.transport.readBlob("/presentation/assets/content", { ...options, query: { path } });
  }
}
