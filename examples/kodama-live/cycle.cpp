#include "task_config.hpp"
#include "app.h"

extern "C" int demo_start_cycle(void) {
    // No live tasks remain. Re-arm the initialization dependency for each run.
    return kodama_level_set(INIT_READY, 0, 0) && app_start();
}
