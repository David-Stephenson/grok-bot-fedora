/*
 * Minimal N-API addon used only when a Cursor-shipped native cannot be
 * found. It loads, exports nothing, and lets guarded require() sites
 * treat the feature as unavailable instead of crashing on dlopen.
 */
#include <node_api.h>

static napi_value Init(napi_env env, napi_value exports) {
  (void)env;
  return exports;
}

NAPI_MODULE(napi_stub, Init)
