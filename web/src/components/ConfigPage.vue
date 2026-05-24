<template>
  <div class="mt-6 space-y-6">
    <div class="glass-card overflow-hidden p-6">
      <div class="pointer-events-none absolute"></div>
      <div class="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-500/10 px-4 py-2 text-sm text-blue-200">
            <span class="inline-block h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_14px_rgba(34,211,238,0.9)]"></span>
            AutoTeam Configuration Center
          </div>
          <h2 class="section-heading">配置面板</h2>
          <p class="section-subtitle max-w-2xl">
            按邮箱服务、远端同步、安全、管理员、巡检、源文件编辑和代理拆成独立分区，避免把所有运行配置堆在一个页面里。
          </p>
        </div>

        <div class="status-badge max-w-sm text-xs leading-6 text-slate-400">
          高频配置前置，低频配置后置；代理等高级项默认折叠，源文件编辑仍然保留。
        </div>
      </div>

      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <div class="glass-card-soft p-4">
          <div class="text-2xl">🧩</div>
          <div class="mt-3 text-sm font-medium text-white">独立配置分区</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">邮箱服务、同步、安全等高频项前置，低频代理项后置，不再混在一张表单里。</div>
        </div>
        <div class="glass-card-soft p-4">
          <div class="text-2xl">☁️</div>
          <div class="mt-3 text-sm font-medium text-white">动态同步配置</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">可增删多个邮箱服务 / 启用远端目标，再按状态展示对应配置。</div>
        </div>
        <div class="glass-card-soft p-4">
          <div class="text-2xl">📝</div>
          <div class="mt-3 text-sm font-medium text-white">源文件编辑保留</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">可视化配置之外，仍可直接维护完整 .env 源文件。</div>
        </div>
      </div>
    </div>

    <div class="glass-card p-4">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="item in visualCategories"
          :key="item.key"
          @click="visualCategory = item.key"
          class="pill-tab flex items-center gap-2"
          :class="visualCategory === item.key
            ? 'pill-tab-active'
            : ''"
        >
          <span class="text-base">{{ item.icon }}</span>
          {{ item.label }}
        </button>
      </div>
    </div>

    <div
      v-if="selectedRuntimeCategory"
      class="glass-card p-6"
    >
      <div class="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
            <span>{{ currentRuntimeCategoryMeta?.icon }}</span>
            {{ currentRuntimeCategoryMeta?.badge }}
          </div>
          <h3 class="section-heading">{{ currentRuntimeCategoryMeta?.title }}</h3>
          <p class="section-subtitle max-w-3xl">
            {{ currentRuntimeCategoryMeta?.description }}
          </p>
          <p
            v-if="currentRuntimeCategoryMeta?.note"
            class="mt-2 text-xs text-slate-500"
          >
            {{ currentRuntimeCategoryMeta.note }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <span
            v-if="runtimeSaved"
            class="status-badge border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
          >
            已保存
          </span>
          <span
            class="status-badge min-w-[84px] justify-center"
            :class="currentRuntimeStatus.class"
          >
            {{ currentRuntimeStatus.label }}
          </span>
        </div>
      </div>

      <div
        v-if="runtimeMessage"
        class="mb-4 rounded-2xl px-4 py-3 text-sm border"
        :class="runtimeMessageClass"
      >
        {{ runtimeMessage }}
      </div>

      <div v-if="runtimeLoading" class="text-sm text-slate-400">
        正在加载当前配置...
      </div>

      <div v-else-if="selectedRuntimeCategory === 'cloudmail'" class="space-y-5">
        <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div class="text-sm font-medium text-white">邮箱服务列表</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                可以同时添加多个 CloudMail / Cloudflare Temp Email / Tempmail 实例；默认服务用于新建账号，已有账号会优先复用自身绑定或唯一域名匹配到的服务。
              </div>
            </div>
            <div class="status-badge text-xs text-slate-400">
              {{ defaultMailService ? `默认：${mailServiceCardTitle(defaultMailService)}` : '未设置默认服务' }}
            </div>
          </div>

          <div class="mt-4 flex flex-wrap gap-3">
            <button class="btn-secondary" @click="addMailService('cloudmail')">
              + 添加 CloudMail
            </button>
            <button class="btn-secondary" @click="addMailService('cloudflare_temp_email')">
              + 添加 Cloudflare Temp Email
            </button>
            <button class="btn-secondary" @click="addMailService('tempmail')">
              + 添加 Tempmail
            </button>
          </div>
        </div>

        <div
          v-if="!mailServices.length"
          class="rounded-2xl border border-dashed border-white/10 bg-white/5 px-4 py-5 text-sm text-slate-400"
        >
          还没有配置任何邮箱服务。先添加一个服务，再设置为默认服务。
        </div>

        <div
          v-for="service in mailServices"
          :key="service.id"
          class="rounded-2xl border border-white/10 bg-white/5 p-5"
        >
          <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <div class="text-sm font-medium text-white">{{ mailServiceCardTitle(service) }}</div>
                <span class="status-badge text-[11px] text-slate-300">
                  {{ mailServiceTypeLabel(service.type) }}
                </span>
                <span
                  v-if="mailServiceDefault === service.id"
                  class="status-badge border-emerald-400/20 bg-emerald-500/10 text-[11px] text-emerald-200"
                >
                  默认新建服务
                </span>
                <span
                  v-if="!isMailServiceComplete(service)"
                  class="status-badge border-amber-400/20 bg-amber-500/10 text-[11px] text-amber-200"
                >
                  待补全
                </span>
              </div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                {{ mailServiceDescription(service.type) }}
              </div>
            </div>

            <div class="flex flex-wrap gap-2">
              <button
                v-if="mailServiceDefault !== service.id"
                class="btn-secondary"
                @click="setDefaultMailService(service.id)"
              >
                设为默认
              </button>
              <button
                class="btn-secondary border-red-500/30 text-red-300 hover:border-red-400/40 hover:text-red-200"
                @click="removeMailService(service.id)"
              >
                删除
              </button>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                服务名称
                <span class="ml-1 text-xs font-normal text-slate-500">（可选）</span>
              </label>
              <input
                v-model="service.name"
                type="text"
                placeholder="例如：CloudMail #1"
                class="input-dark"
              />
            </div>

            <div
              v-for="field in mailServiceFields(service)"
              :key="`${service.id}-${field.key}`"
              class="rounded-2xl border border-white/10 bg-slate-950/25 p-4"
            >
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.label }}
                <span v-if="field.required" class="text-red-400">*</span>
                <div v-if="field.hint" class="mt-1 text-[11px] font-normal text-slate-500 break-all">
                  {{ field.hint }}
                </div>
              </label>
              <input
                v-model="service[field.key]"
                :type="field.inputType || 'text'"
                :placeholder="field.placeholder || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            保存后会立即热加载。新建账号会使用默认服务；已有账号会优先按 `mail_service_id` 或唯一邮箱域名匹配对应服务。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else-if="selectedRuntimeCategory === 'sync'" class="space-y-5">
        <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4 flex items-center justify-between gap-4">
            <div>
              <div class="text-sm font-medium text-white">同步目标开关</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                可同时启用多个远端。界面只展示当前已启用目标的详细配置。
              </div>
            </div>
            <div class="status-badge text-xs text-slate-400">
              {{ enabledSyncTargetsText }}
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div v-for="field in syncToggleFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
              </label>
              <select
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option value="true">启用</option>
                <option value="false">关闭</option>
              </select>
            </div>
          </div>
        </div>

        <div v-if="syncCpaEnabled" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">CPA</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              为已启用的 CPA 远端填写连接地址和管理密钥。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in syncCpaFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <input
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-if="syncSub2apiEnabled" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">Sub2API</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              为已启用的 Sub2API 远端填写地址、管理员邮箱、密码和可选分组。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in syncSub2apiConnectionFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                <div v-if="sub2apiFieldHint(field.key)" class="mt-1 font-mono text-[11px] font-normal text-slate-500 break-all">
                  {{ sub2apiFieldHint(field.key) }}
                </div>
              </label>
              <input
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-if="syncSub2apiEnabled" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">Sub2API 默认账号设置</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              新创建的 Sub2API 账号会自动带上这些默认参数和可选代理绑定；已存在账号默认不覆盖，只有开启“覆盖账号设置”后才会在每次同步时强制统一（代理绑定仍只在新建账号时写入）。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in syncSub2apiDefaultFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                <div v-if="sub2apiFieldHint(field.key)" class="mt-1 font-mono text-[11px] font-normal text-slate-500 break-all">
                  {{ sub2apiFieldHint(field.key) }}
                </div>
              </label>
              <select
                v-if="isBooleanStringField(field.key)"
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
              <select
                v-else-if="isWsModeField(field.key)"
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option value="off">off</option>
                <option value="ctx_pool">ctx_pool</option>
                <option value="passthrough">passthrough</option>
              </select>
              <input
                v-else
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :step="fieldInputStep(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-if="!syncCpaEnabled && !syncSub2apiEnabled" class="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-slate-400">
          当前还没有启用任何远端同步目标。先打开上面的开关，再填写对应远端配置。
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            保存后会立即热加载；账号池操作会根据当前已启用远端决定后续同步行为。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else-if="selectedRuntimeCategory === 'proxy'" class="space-y-4">
        <div class="rounded-2xl border border-white/10 bg-white/5 p-4">
          <button
            @click="proxyExpanded = !proxyExpanded"
            class="flex w-full items-center justify-between gap-4 text-left"
          >
            <div>
              <div class="text-sm font-medium text-white">高级代理设置</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                低频配置，默认折叠。只有浏览器流量需要单独代理时才建议填写。
              </div>
            </div>
            <span class="text-xs text-slate-400">{{ proxyExpanded ? '收起' : '展开' }}</span>
          </button>

          <div v-if="proxyExpanded" class="mt-4 space-y-5">
            <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div class="mb-4">
                <div class="text-sm font-medium text-white">EasyProxy 接管</div>
                <div class="mt-1 text-xs leading-5 text-slate-400">
                  启用后，AutoTeam 会优先按 `EASYPROXY_MASTER_MODE` 决定浏览器和 HTTP 流量是否走 EasyProxy 池化端口；`follow_pool` 表示走 `proxy_host:pool_port`，`direct` 表示直连。
                </div>
              </div>

              <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div v-for="field in easyproxyFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                  <label class="mb-2 block text-sm font-medium text-slate-300">
                    {{ field.prompt }}
                    <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                  </label>
                  <select
                    v-if="isEasyproxyEnabledField(field.key)"
                    v-model="runtimeForm[field.key]"
                    class="input-dark"
                  >
                    <option value="true">启用</option>
                    <option value="false">关闭</option>
                  </select>
                  <select
                    v-else-if="isEasyproxyMasterModeField(field.key)"
                    v-model="runtimeForm[field.key]"
                    class="input-dark"
                  >
                    <option value="direct">direct</option>
                    <option value="follow_pool">follow_pool</option>
                  </select>
                  <input
                    v-else
                    v-model="runtimeForm[field.key]"
                    :type="fieldInputType(field.key)"
                    :step="fieldInputStep(field.key)"
                    :placeholder="field.default || ''"
                    class="input-dark"
                  />
                </div>
              </div>
            </div>

            <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div class="text-sm font-medium text-white">EasyProxy 状态 / 端口管理</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    读取 EasyProxy 管理 API 的真实 hybrid 端口列表，并叠加本地冷却黑名单。浏览器启动时会从“可选”端口里真随机挑选，不再固定从 `24001` 开始试。
                  </div>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    class="btn-secondary"
                    :disabled="easyproxyLoading"
                    @click="probeEasyProxy"
                  >
                    {{ easyproxyLoading ? '刷新中...' : '刷新状态' }}
                  </button>
                  <button
                    class="btn-secondary"
                    :disabled="easyproxyReleasing || !(easyproxySummary?.local_blacklisted > 0)"
                    @click="releaseEasyProxy()"
                  >
                    {{ easyproxyReleasing ? '释放中...' : '释放全部本地黑名单' }}
                  </button>
                </div>
              </div>

              <div class="mt-4 flex flex-wrap gap-2 text-xs">
                <span class="status-badge text-slate-300">
                  {{ easyproxyEnabled ? 'EasyProxy 已启用' : 'EasyProxy 未启用' }}
                </span>
                <span v-if="easyproxyStatus?.ok" class="status-badge border-emerald-400/20 bg-emerald-500/10 text-emerald-200">
                  可选 {{ easyproxySummary?.selectable ?? 0 }} / {{ easyproxySummary?.total ?? 0 }}
                </span>
                <span v-if="easyproxyStatus?.ok" class="status-badge text-slate-300">
                  远端可用 {{ easyproxySummary?.remote_available ?? 0 }}
                </span>
                <span v-if="easyproxyStatus?.ok" class="status-badge text-slate-300">
                  本地黑名单 {{ easyproxySummary?.local_blacklisted ?? 0 }}
                </span>
                <span class="status-badge text-slate-300">
                  Master {{ String(runtimeForm.EASYPROXY_MASTER_MODE || 'direct') === 'follow_pool' ? '走池端口' : '直连' }}
                </span>
              </div>

              <p class="mt-3 text-xs leading-5 text-slate-500">
                说明：这里按管理 API 返回的真实端口筛选 `EASYPROXY_PORT_MIN ~ EASYPROXY_PORT_MAX`，不会假设端口一定连续，也不会优先固定选最小端口。
              </p>

              <div v-if="easyproxyStatus?.error" class="mt-4 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                {{ easyproxyStatus.error }}
              </div>

              <div v-if="easyproxyStatus?.ok" class="mt-4 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/25">
                <div class="overflow-x-auto">
                  <table class="min-w-full text-sm">
                    <thead class="border-b border-white/10 bg-white/5 text-slate-300">
                      <tr>
                        <th class="px-4 py-3 text-left font-medium">端口</th>
                        <th class="px-4 py-3 text-left font-medium">标签</th>
                        <th class="px-4 py-3 text-left font-medium">状态</th>
                        <th class="px-4 py-3 text-left font-medium">说明</th>
                        <th class="px-4 py-3 text-left font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="entry in easyproxyPorts"
                        :key="entry.port"
                        class="border-b border-white/5 last:border-b-0"
                      >
                        <td class="px-4 py-3 font-mono text-slate-200">{{ entry.port }}</td>
                        <td class="px-4 py-3 text-slate-300">{{ entry.tag || entry.name || '-' }}</td>
                        <td class="px-4 py-3">
                          <span
                            v-if="entry.selectable"
                            class="status-badge border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                          >
                            可选
                          </span>
                          <span
                            v-else-if="entry.local_blacklisted"
                            class="status-badge border-amber-400/20 bg-amber-500/10 text-amber-200"
                          >
                            本地拉黑
                          </span>
                          <span
                            v-else-if="entry.remote_blacklisted"
                            class="status-badge border-amber-400/20 bg-amber-500/10 text-amber-200"
                          >
                            远端拉黑
                          </span>
                          <span v-else class="status-badge text-slate-300">
                            {{ entry.available ? '占用 / 不可选' : '不可用' }}
                          </span>
                        </td>
                        <td
                          class="max-w-xl px-4 py-3 text-xs leading-5 text-slate-400"
                          :title="entry.local_blacklist_reason || entry.last_error || ''"
                        >
                          {{ entry.local_blacklist_reason || entry.last_error || '-' }}
                        </td>
                        <td class="px-4 py-3">
                          <button
                            v-if="entry.local_blacklisted || entry.remote_blacklisted"
                            class="text-xs text-cyan-300 underline decoration-cyan-400/40 underline-offset-4 hover:text-cyan-200 disabled:cursor-not-allowed disabled:text-slate-500"
                            :disabled="easyproxyReleasing"
                            @click="releaseEasyProxy([entry.port])"
                          >
                            释放
                          </button>
                          <span v-else class="text-xs text-slate-500">-</span>
                        </td>
                      </tr>
                      <tr v-if="!easyproxyPorts.length">
                        <td colspan="5" class="px-4 py-4 text-center text-slate-500">
                          当前范围内没有可展示的 hybrid 端口
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div class="mb-4">
                <div class="text-sm font-medium text-white">手动 Playwright 代理</div>
                <div class="mt-1 text-xs leading-5 text-slate-400">
                  只在没有启用 EasyProxy，或者你明确想走单一固定代理时填写。启用 EasyProxy 后，这里的代理 URL 会被接管逻辑覆盖。
                </div>
              </div>

              <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div v-for="field in manualProxyFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                  <label class="mb-2 block text-sm font-medium text-slate-300">
                    {{ field.prompt }}
                    <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                  </label>
                  <input
                    v-model="runtimeForm[field.key]"
                    :type="fieldInputType(field.key)"
                    :placeholder="field.default || ''"
                    class="input-dark"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            推荐只在确实需要代理 Playwright 浏览器流量时启用，并配合绕过列表避免本地回调误走代理。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else class="space-y-4">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="field in currentRuntimeFields" :key="field.key" class="rounded-2xl border border-white/10 bg-white/5 p-4">
            <label class="mb-2 block text-sm font-medium text-slate-300">
              {{ field.prompt }}
              <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              <span v-if="field.key === 'API_KEY'" class="ml-1 text-xs text-slate-500">（留空自动生成）</span>
            </label>
            <input
              v-model="runtimeForm[field.key]"
              :type="fieldInputType(field.key)"
              :placeholder="field.default || ''"
              class="input-dark"
            />
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            {{ currentRuntimeCategoryMeta?.footer }}
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>
    </div>

    <Settings
      v-else-if="visualCategory === 'admin'"
      :admin-status="adminStatus"
      :codex-status="codexStatus"
      section="admin"
      @refresh="$emit('refresh')"
      @admin-progress="$emit('admin-progress')"
    />

    <Settings
      v-else-if="visualCategory === 'auto-check'"
      :admin-status="adminStatus"
      :codex-status="codexStatus"
      section="auto-check"
      @refresh="$emit('refresh')"
      @admin-progress="$emit('admin-progress')"
    />

    <div v-else-if="visualCategory === 'source'" class="glass-card space-y-4 p-6">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
            <span>📝</span>
            Source Editor
          </div>
          <h3 class="section-heading">源文件编辑</h3>
          <p class="section-subtitle">
            直接编辑 .env 源文件。保存后会立即重载并校验邮箱服务 / 远端同步配置。
          </p>
        </div>
        <div class="status-badge break-all font-mono text-[11px] text-slate-400">
          {{ sourcePath || '.env' }}
        </div>
      </div>

      <div
        v-if="sourceMessage"
        class="rounded-2xl px-4 py-3 text-sm border"
        :class="sourceMessageClass"
      >
        {{ sourceMessage }}
      </div>

      <textarea
        v-model="sourceContent"
        rows="20"
        spellcheck="false"
        class="textarea-dark min-h-[420px] font-mono"
        placeholder="在这里编辑 .env 内容"
      />

      <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
        <p class="text-xs leading-6 text-slate-400">
          这里是原始文本模式，适合你直接粘贴或手工维护完整 .env。
        </p>
        <div class="flex gap-2">
          <button
            @click="loadSourceConfig"
            :disabled="sourceLoading || sourceSaving"
            class="btn-secondary"
          >
            {{ sourceLoading ? '加载中...' : '重新读取' }}
          </button>
          <button
            @click="saveSourceConfig"
            :disabled="sourceLoading || sourceSaving"
            class="btn-primary"
          >
            {{ sourceSaving ? '保存中...' : '保存源文件' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, setApiKey } from '../api.js'
import Settings from './Settings.vue'

defineProps({
  adminStatus: {
    type: Object,
    default: null,
  },
  codexStatus: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh', 'admin-progress'])

const runtimeCategoryKeys = {
  cloudmail: ['MAIL_PROVIDER', 'CLOUDMAIL_BASE_URL', 'CLOUDMAIL_EMAIL', 'CLOUDMAIL_PASSWORD', 'CLOUDMAIL_DOMAIN', 'CF_TEMP_EMAIL_BASE_URL', 'CF_TEMP_EMAIL_ADMIN_PASSWORD', 'CF_TEMP_EMAIL_DOMAIN', 'TEMPMAIL_BASE_URL', 'TEMPMAIL_API_KEY', 'TEMPMAIL_DOMAIN'],
  sync: [
    'SYNC_TARGET_CPA',
    'SYNC_TARGET_SUB2API',
    'CPA_URL',
    'CPA_KEY',
    'SUB2API_URL',
    'SUB2API_EMAIL',
    'SUB2API_PASSWORD',
    'SUB2API_GROUP',
    'SUB2API_CONCURRENCY',
    'SUB2API_PRIORITY',
    'SUB2API_RATE_MULTIPLIER',
    'SUB2API_AUTO_PAUSE_ON_EXPIRED',
    'SUB2API_MODEL_WHITELIST',
    'SUB2API_OPENAI_WS_MODE',
    'SUB2API_OPENAI_PASSTHROUGH',
    'SUB2API_OVERWRITE_ACCOUNT_SETTINGS',
    'SUB2API_PROXY',
  ],
  proxy: [
    'EASYPROXY_ENABLED',
    'EASYPROXY_MANAGEMENT_URL',
    'EASYPROXY_PASSWORD',
    'EASYPROXY_PROXY_HOST',
    'EASYPROXY_POOL_PORT',
    'EASYPROXY_PORT_MIN',
    'EASYPROXY_PORT_MAX',
    'EASYPROXY_COOLDOWN_MINUTES',
    'EASYPROXY_MASTER_MODE',
    'PLAYWRIGHT_PROXY_URL',
    'PLAYWRIGHT_PROXY_BYPASS',
  ],
  security: ['API_KEY'],
}

const runtimeCategoryMeta = {
  cloudmail: {
    icon: '📧',
    badge: 'Mail Services',
    title: '邮箱服务配置',
    description: '配置自动注册和收验证码所需的邮箱后端。现在支持同时维护多个 CloudMail / Cloudflare Temp Email / Tempmail 实例，并指定默认新建服务。',
    note: '已有账号会优先按账号自身保存的 mail_service_id 或唯一邮箱域名匹配服务；存在歧义时不会盲猜。',
    footer: '邮箱服务配置保存后会立即热加载；之后的新建、复用和验证码轮询都会按最新服务列表执行。',
  },
  sync: {
    icon: '☁️',
    badge: 'Remote Sync',
    title: '远端同步',
    description: '先选择启用的远端同步目标，再填写对应的连接信息。账号池操作会根据这里的启用状态决定同步到哪些远端。',
    note: '支持同时启用 CPA 和 Sub2API；界面只显示当前已启用目标的详细配置。',
  },
  proxy: {
    icon: '🛰️',
    badge: 'Proxy / Advanced',
    title: '代理 / 高级',
    description: '用于配置 EasyProxy 接管逻辑，或手动指定 Playwright 浏览器代理。属于低频项，默认折叠，避免把主配置界面堆得过满。',
    note: '启用 EasyProxy 后，代理接管优先级高于手动 Playwright 代理；本地回调场景通常还需要设置 bypass。',
  },
  security: {
    icon: '🔐',
    badge: 'Security',
    title: '安全 / 访问控制',
    description: '入口级配置集中放在这里。API Key 决定 Web 面板和 HTTP API 的访问控制，不再和其他运行参数混在一起。',
    note: '留空会自动生成新的 API Key；保存后前端会立即切换到新的密钥。',
    footer: '这是控制面板和 API 的入口密钥。修改后会立即生效，并同步刷新当前浏览器里的 API Key。',
  },
}

const visualCategories = [
  { key: 'cloudmail', label: '邮箱服务', icon: '📧' },
  { key: 'sync', label: '远端同步', icon: '☁️' },
  { key: 'security', label: '安全 / 访问控制', icon: '🔐' },
  { key: 'admin', label: '管理员 / 主号', icon: '👤' },
  { key: 'auto-check', label: '巡检设置', icon: '🔄' },
  { key: 'source', label: '源文件编辑', icon: '📝' },
  { key: 'proxy', label: '代理 / 高级', icon: '🛰️' },
]

const visualCategory = ref('cloudmail')
const proxyExpanded = ref(false)

const runtimeFields = ref([])
const runtimeForm = reactive({})
const mailServices = ref([])
const mailServiceDefault = ref('')
const runtimeLoading = ref(false)
const runtimeSaving = ref(false)
const runtimeSaved = ref(false)
const runtimeMessage = ref('')
const runtimeMessageClass = ref('')
const easyproxyStatus = ref(null)
const easyproxyReleasing = ref(false)

const sourcePath = ref('')
const sourceContent = ref('')
const sourceLoading = ref(false)
const sourceSaving = ref(false)
const sourceLoaded = ref(false)
const sourceMessage = ref('')
const sourceMessageClass = ref('')
const runtimeRequiredKeys = new Set(['API_KEY'])
const sub2apiFieldHints = {
  SUB2API_URL: 'ENV: SUB2API_URL · Sub2API API base URL',
  SUB2API_EMAIL: 'ENV: SUB2API_EMAIL · login.email',
  SUB2API_PASSWORD: 'ENV: SUB2API_PASSWORD · login.password',
  SUB2API_GROUP: 'ENV: SUB2API_GROUP · group_ids',
  SUB2API_PROXY: 'ENV: SUB2API_PROXY · account.proxy_id（ID 或名称，仅账号池新建时写入）',
  SUB2API_CONCURRENCY: 'ENV: SUB2API_CONCURRENCY · account.concurrency',
  SUB2API_PRIORITY: 'ENV: SUB2API_PRIORITY · account.priority',
  SUB2API_RATE_MULTIPLIER: 'ENV: SUB2API_RATE_MULTIPLIER · account.rate_multiplier',
  SUB2API_AUTO_PAUSE_ON_EXPIRED: 'ENV: SUB2API_AUTO_PAUSE_ON_EXPIRED · account.auto_pause_on_expired',
  SUB2API_MODEL_WHITELIST: 'ENV: SUB2API_MODEL_WHITELIST · credentials.model_mapping',
  SUB2API_OPENAI_WS_MODE: 'ENV: SUB2API_OPENAI_WS_MODE · extra.openai_oauth_responses_websockets_v2_mode / enabled',
  SUB2API_OPENAI_PASSTHROUGH: 'ENV: SUB2API_OPENAI_PASSTHROUGH · extra.openai_passthrough',
  SUB2API_OVERWRITE_ACCOUNT_SETTINGS: 'ENV: SUB2API_OVERWRITE_ACCOUNT_SETTINGS · AutoTeam overwrite switch',
}

const mailServiceFieldMeta = {
  cloudmail: [
    {
      key: 'base_url',
      label: 'CloudMail API 地址',
      required: true,
      placeholder: 'https://your-cloudmail.com/api',
    },
    {
      key: 'email',
      label: 'CloudMail 登录邮箱',
      required: true,
      placeholder: 'admin@example.com',
    },
    {
      key: 'password',
      label: 'CloudMail 登录密码',
      required: true,
      inputType: 'password',
    },
    {
      key: 'domain',
      label: 'CloudMail 邮箱域名',
      required: true,
      placeholder: 'example.com 或 @example.com',
      hint: '用于自动匹配已有账号所属邮箱服务',
    },
  ],
  cloudflare_temp_email: [
    {
      key: 'base_url',
      label: 'Cloudflare Temp Email API 地址',
      required: true,
      placeholder: 'https://temp-email-api.example.com',
    },
    {
      key: 'admin_password',
      label: '管理员密码',
      required: true,
      inputType: 'password',
    },
    {
      key: 'domain',
      label: '邮箱域名',
      required: false,
      placeholder: '可留空，例如 mail.example.com',
      hint: '可留空；留空时由 tempmail 后端随机分配域名。若填写则可用于自动匹配已有账号所属邮箱服务',
    },
  ],
  tempmail: [
    {
      key: 'base_url',
      label: 'Tempmail API 地址',
      required: true,
      placeholder: 'https://tempmail-api.example.com',
    },
    {
      key: 'api_key',
      label: 'API Key',
      required: true,
      inputType: 'password',
    },
    {
      key: 'domain',
      label: '邮箱域名',
      required: false,
      placeholder: '可留空，例如 mail.example.com',
      hint: '可留空；留空时由 tempmail 后端随机分配域名。若填写则可用于自动匹配已有账号所属邮箱服务',
    },
  ],
}

const selectedRuntimeCategory = computed(() => runtimeCategoryKeys[visualCategory.value] ? visualCategory.value : '')
const currentRuntimeCategoryMeta = computed(() => runtimeCategoryMeta[selectedRuntimeCategory.value] || null)

function fieldByKey(key) {
  return runtimeFields.value.find(field => field.key === key) || null
}

function sub2apiFieldHint(key) {
  return sub2apiFieldHints[key] || ''
}

function fieldsByKeys(keys) {
  return keys
    .map(key => fieldByKey(key))
    .filter(Boolean)
}

const securityFields = computed(() => fieldsByKeys(runtimeCategoryKeys.security))
const proxyFields = computed(() => fieldsByKeys(runtimeCategoryKeys.proxy))
const easyproxyFields = computed(() => fieldsByKeys([
  'EASYPROXY_ENABLED',
  'EASYPROXY_MANAGEMENT_URL',
  'EASYPROXY_PASSWORD',
  'EASYPROXY_PROXY_HOST',
  'EASYPROXY_POOL_PORT',
  'EASYPROXY_PORT_MIN',
  'EASYPROXY_PORT_MAX',
  'EASYPROXY_COOLDOWN_MINUTES',
  'EASYPROXY_MASTER_MODE',
]))
const manualProxyFields = computed(() => fieldsByKeys(['PLAYWRIGHT_PROXY_URL', 'PLAYWRIGHT_PROXY_BYPASS']))
const syncToggleFields = computed(() => fieldsByKeys(['SYNC_TARGET_CPA', 'SYNC_TARGET_SUB2API']))
const defaultMailService = computed(() => mailServices.value.find(service => service.id === mailServiceDefault.value) || null)

const syncCpaEnabled = computed(() => String(runtimeForm.SYNC_TARGET_CPA || '').toLowerCase() === 'true')
const syncSub2apiEnabled = computed(() => String(runtimeForm.SYNC_TARGET_SUB2API || '').toLowerCase() === 'true')
const easyproxyEnabled = computed(() => String(runtimeForm.EASYPROXY_ENABLED || '').toLowerCase() === 'true')
const manualProxyConfigured = computed(() => Boolean(String(runtimeForm.PLAYWRIGHT_PROXY_URL || '').trim()))
const easyproxyLoading = computed(() => Boolean(easyproxyStatus.value?.running))
const easyproxyPorts = computed(() => Array.isArray(easyproxyStatus.value?.ports) ? easyproxyStatus.value.ports : [])
const easyproxySummary = computed(() => easyproxyStatus.value?.summary || null)
const syncCpaFields = computed(() => syncCpaEnabled.value ? fieldsByKeys(['CPA_URL', 'CPA_KEY']) : [])
const syncSub2apiConnectionFields = computed(() => syncSub2apiEnabled.value
  ? fieldsByKeys(['SUB2API_URL', 'SUB2API_EMAIL', 'SUB2API_PASSWORD', 'SUB2API_GROUP'])
  : [])
const syncSub2apiDefaultFields = computed(() => syncSub2apiEnabled.value
  ? fieldsByKeys([
      'SUB2API_CONCURRENCY',
      'SUB2API_PRIORITY',
      'SUB2API_RATE_MULTIPLIER',
      'SUB2API_AUTO_PAUSE_ON_EXPIRED',
      'SUB2API_MODEL_WHITELIST',
      'SUB2API_OPENAI_WS_MODE',
      'SUB2API_OPENAI_PASSTHROUGH',
      'SUB2API_OVERWRITE_ACCOUNT_SETTINGS',
      'SUB2API_PROXY',
    ])
  : [])

const currentRuntimeFields = computed(() => {
  if (selectedRuntimeCategory.value === 'security') {
    return securityFields.value
  }
  return []
})

const enabledSyncTargetsText = computed(() => {
  const targets = []
  if (syncCpaEnabled.value) {
    targets.push('CPA')
  }
  if (syncSub2apiEnabled.value) {
    targets.push('Sub2API')
  }
  return targets.length ? `已启用：${targets.join(' + ')}` : '当前未启用远端'
})

const currentRuntimeStatus = computed(() => {
  if (!selectedRuntimeCategory.value) {
    return {
      label: '',
      class: 'border-white/10 bg-white/5 text-slate-400',
    }
  }

  if (selectedRuntimeCategory.value === 'sync') {
    if (!syncCpaEnabled.value && !syncSub2apiEnabled.value) {
      return {
        label: '未启用',
        class: 'border-white/10 bg-white/5 text-slate-400',
      }
    }

    const cpaReady = !syncCpaEnabled.value || syncCpaFields.value.every(field => !isRuntimeRequired(field) || field.configured)
    const sub2apiReady = !syncSub2apiEnabled.value || syncSub2apiConnectionFields.value.every(field => !isRuntimeRequired(field) || field.configured)

    return cpaReady && sub2apiReady
      ? {
          label: '已配置',
          class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        }
      : {
          label: '未配置',
          class: 'border-red-400/20 bg-red-500/10 text-red-200',
        }
  }

  if (selectedRuntimeCategory.value === 'proxy') {
    return easyproxyEnabled.value
      ? {
          label: 'EasyProxy',
          class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        }
      : manualProxyConfigured.value
        ? {
            label: '已设置',
            class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
          }
        : {
            label: '未设置',
            class: 'border-white/10 bg-white/5 text-slate-400',
          }
  }

  if (selectedRuntimeCategory.value === 'cloudmail') {
    if (!mailServices.value.length) {
      return {
        label: '未配置',
        class: 'border-red-400/20 bg-red-500/10 text-red-200',
      }
    }
    if (!defaultMailService.value) {
      return {
        label: '未设默认',
        class: 'border-amber-400/20 bg-amber-500/10 text-amber-200',
      }
    }
    if (mailServices.value.some(service => !isMailServiceComplete(service))) {
      return {
        label: '待补全',
        class: 'border-amber-400/20 bg-amber-500/10 text-amber-200',
      }
    }
    return {
      label: '已配置',
      class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
    }
  }

  const fields = currentRuntimeFields.value
  const configured = fields.length > 0 && fields.every(field => !isRuntimeRequired(field) || field.configured)

  return configured
    ? {
        label: '已配置',
        class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
      }
    : {
        label: '未配置',
        class: 'border-red-400/20 bg-red-500/10 text-red-200',
      }
})

function setRuntimeMessage(text, type = 'success') {
  runtimeMessage.value = text
  runtimeMessageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setRuntimeMessage._timer)
  setRuntimeMessage._timer = window.setTimeout(() => {
    runtimeMessage.value = ''
  }, 8000)
}

function setSourceMessage(text, type = 'success') {
  sourceMessage.value = text
  sourceMessageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setSourceMessage._timer)
  setSourceMessage._timer = window.setTimeout(() => {
    sourceMessage.value = ''
  }, 8000)
}

function fieldInputType(key) {
  if ([
    'SUB2API_CONCURRENCY',
    'SUB2API_PRIORITY',
    'SUB2API_RATE_MULTIPLIER',
    'EASYPROXY_POOL_PORT',
    'EASYPROXY_PORT_MIN',
    'EASYPROXY_PORT_MAX',
    'EASYPROXY_COOLDOWN_MINUTES',
  ].includes(key)) {
    return 'number'
  }
  return key.includes('PASSWORD') || key.includes('KEY') ? 'password' : 'text'
}

function isToggleField(key) {
  return key === 'SYNC_TARGET_CPA' || key === 'SYNC_TARGET_SUB2API'
}

function isBooleanStringField(key) {
  return isToggleField(key) || [
    'SUB2API_AUTO_PAUSE_ON_EXPIRED',
    'SUB2API_OPENAI_PASSTHROUGH',
    'SUB2API_OVERWRITE_ACCOUNT_SETTINGS',
    'EASYPROXY_ENABLED',
  ].includes(key)
}

function isWsModeField(key) {
  return key === 'SUB2API_OPENAI_WS_MODE'
}

function isEasyproxyEnabledField(key) {
  return key === 'EASYPROXY_ENABLED'
}

function isEasyproxyMasterModeField(key) {
  return key === 'EASYPROXY_MASTER_MODE'
}

function fieldInputStep(key) {
  if (key === 'SUB2API_RATE_MULTIPLIER') {
    return '0.001'
  }
  if (
    key === 'SUB2API_CONCURRENCY'
    || key === 'SUB2API_PRIORITY'
    || key === 'EASYPROXY_POOL_PORT'
    || key === 'EASYPROXY_PORT_MIN'
    || key === 'EASYPROXY_PORT_MAX'
    || key === 'EASYPROXY_COOLDOWN_MINUTES'
  ) {
    return '1'
  }
  return undefined
}

function createMailService(type = 'cloudmail') {
  const typeText = String(type || '').toLowerCase()
  const normalizedType = typeText === 'cloudflare_temp_email'
    ? 'cloudflare_temp_email'
    : typeText === 'tempmail'
      ? 'tempmail'
      : 'cloudmail'
  const randomPart = Math.random().toString(36).slice(2, 8)
  return {
    id: `mailsvc-${Date.now().toString(36)}-${randomPart}`,
    type: normalizedType,
    name: '',
    base_url: '',
    domain: '',
    email: '',
    password: '',
    admin_password: '',
    api_key: '',
  }
}

function normalizeMailService(service) {
  const template = createMailService(service?.type)
  return {
    ...template,
    id: String(service?.id || template.id),
    name: String(service?.name || ''),
    base_url: String(service?.base_url || ''),
    domain: String(service?.domain || ''),
    email: String(service?.email || ''),
    password: String(service?.password || ''),
    admin_password: String(service?.admin_password || ''),
    api_key: String(service?.api_key || ''),
  }
}

function sanitizeMailService(service) {
  const normalized = normalizeMailService(service)
  normalized.domain = normalized.domain.trim()
  if (normalized.type === 'cloudflare_temp_email') {
    delete normalized.email
    delete normalized.password
    delete normalized.api_key
  } else if (normalized.type === 'tempmail') {
    delete normalized.email
    delete normalized.password
    delete normalized.admin_password
  } else {
    delete normalized.admin_password
    delete normalized.api_key
  }
  return normalized
}

function mailServiceTypeLabel(type) {
  if (type === 'cloudflare_temp_email') {
    return 'Cloudflare Temp Email'
  }
  if (type === 'tempmail') {
    return 'Tempmail'
  }
  return 'CloudMail'
}

function mailServiceDescription(type) {
  return type === 'cloudflare_temp_email'
    ? '填写管理端 API 地址、管理员密码和对应邮箱域名。'
    : type === 'tempmail'
      ? '填写自建 tempmail 后端 API 地址和 API Key；邮箱域名可留空，交给后端随机分配。'
      : '填写 CloudMail API 地址、管理员账号密码和对应邮箱域名。'
}

function mailServiceFields(service) {
  return mailServiceFieldMeta[service?.type] || mailServiceFieldMeta.cloudmail
}

function isMailServiceComplete(service) {
  return mailServiceFields(service).every(field => {
    if (!field.required) {
      return true
    }
    return String(service?.[field.key] || '').trim() !== ''
  })
}

function mailServiceCardTitle(service) {
  const name = String(service?.name || '').trim()
  if (name) {
    return name
  }
  const label = mailServiceTypeLabel(service?.type)
  const domain = String(service?.domain || '').trim()
  return domain ? `${label} (${domain})` : label
}

function ensureMailServiceDefault() {
  const existingIds = new Set(mailServices.value.map(service => service.id))
  if (mailServiceDefault.value && existingIds.has(mailServiceDefault.value)) {
    return
  }
  mailServiceDefault.value = mailServices.value[0]?.id || ''
}

function addMailService(type) {
  mailServices.value = [...mailServices.value, createMailService(type)]
  ensureMailServiceDefault()
}

function removeMailService(id) {
  mailServices.value = mailServices.value.filter(service => service.id !== id)
  ensureMailServiceDefault()
}

function setDefaultMailService(id) {
  mailServiceDefault.value = id
}

function isRuntimeRequired(field) {
  return Boolean(field?.runtime_required) || runtimeRequiredKeys.has(field?.key)
}

function normalizeRuntimeFieldValue(field) {
  const value = field?.value ?? field?.default ?? ''
  if (isBooleanStringField(field?.key)) {
    return String(value).toLowerCase() === 'true' ? 'true' : 'false'
  }
  if (isWsModeField(field?.key)) {
    const mode = String(value || '').toLowerCase()
    return ['off', 'ctx_pool', 'passthrough'].includes(mode) ? mode : 'off'
  }
  if (isEasyproxyMasterModeField(field?.key)) {
    const mode = String(value || '').toLowerCase()
    return ['direct', 'follow_pool'].includes(mode) ? mode : 'direct'
  }
  return value
}

async function loadRuntimeConfig() {
  runtimeLoading.value = true
  try {
    const result = await api.getRuntimeConfig()
    runtimeFields.value = result.fields || []
    mailServices.value = Array.isArray(result.mail_services)
      ? result.mail_services.map(service => normalizeMailService(service))
      : []
    mailServiceDefault.value = String(result.mail_service_default || '')
    ensureMailServiceDefault()

    for (const key of Object.keys(runtimeForm)) {
      if (!runtimeFields.value.find(field => field.key === key)) {
        delete runtimeForm[key]
      }
    }
    for (const field of runtimeFields.value) {
      runtimeForm[field.key] = normalizeRuntimeFieldValue(field)
    }
  } catch (e) {
    console.error('加载运行时配置失败:', e)
    setRuntimeMessage('加载运行时配置失败: ' + e.message, 'error')
  } finally {
    runtimeLoading.value = false
  }
}

async function saveRuntimeConfig() {
  runtimeSaving.value = true
  runtimeSaved.value = false
  try {
    const payload = {}
    for (const field of runtimeFields.value) {
      const value = runtimeForm[field.key]
      payload[field.key] = value == null ? '' : String(value)
    }
    const sanitizedServices = mailServices.value.map(service => sanitizeMailService(service))
    const sanitizedDefault = sanitizedServices.some(service => service.id === mailServiceDefault.value)
      ? mailServiceDefault.value
      : sanitizedServices[0]?.id || ''
    payload.mail_services = sanitizedServices
    payload.mail_service_default = sanitizedDefault
    const result = await api.saveRuntimeConfig(payload)
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    setRuntimeMessage(result.message || '配置保存成功')
    runtimeSaved.value = true
    window.setTimeout(() => {
      runtimeSaved.value = false
    }, 3000)
    await loadRuntimeConfig()
    if (selectedRuntimeCategory.value === 'proxy') {
      if (easyproxyEnabled.value) {
        await probeEasyProxy()
      } else {
        easyproxyStatus.value = null
      }
    }
    emit('refresh')
  } catch (e) {
    setRuntimeMessage(e.message, 'error')
  } finally {
    runtimeSaving.value = false
  }
}

async function probeEasyProxy() {
  easyproxyStatus.value = { running: true }
  try {
    easyproxyStatus.value = await api.easyproxyStatus()
  } catch (e) {
    easyproxyStatus.value = { ok: false, error: e.message }
  }
}

async function releaseEasyProxy(ports = null) {
  easyproxyReleasing.value = true
  try {
    easyproxyStatus.value = await api.easyproxyRelease({ ports, remote: true })
    setRuntimeMessage('EasyProxy 端口状态已更新')
  } catch (e) {
    setRuntimeMessage(`释放端口失败: ${e.message}`, 'error')
  } finally {
    easyproxyReleasing.value = false
  }
}

async function loadSourceConfig() {
  sourceLoading.value = true
  try {
    const result = await api.getRuntimeConfigSource()
    sourcePath.value = result.path || '.env'
    sourceContent.value = result.content || ''
    sourceLoaded.value = true
  } catch (e) {
    console.error('加载源文件失败:', e)
    setSourceMessage('加载源文件失败: ' + e.message, 'error')
  } finally {
    sourceLoading.value = false
  }
}

async function saveSourceConfig() {
  sourceSaving.value = true
  try {
    const result = await api.saveRuntimeConfigSource({ content: sourceContent.value })
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    setSourceMessage(result.message || '源文件保存成功')
    await Promise.all([loadSourceConfig(), loadRuntimeConfig()])
    emit('refresh')
  } catch (e) {
    setSourceMessage(e.message, 'error')
  } finally {
    sourceSaving.value = false
  }
}

watch(visualCategory, async (next) => {
  if (next === 'source' && !sourceLoaded.value) {
    await loadSourceConfig()
    return
  }
  if (next === 'proxy') {
    if (easyproxyEnabled.value) {
      await probeEasyProxy()
    } else {
      easyproxyStatus.value = null
    }
  }
})

onMounted(async () => {
  await loadRuntimeConfig()
})
</script>
