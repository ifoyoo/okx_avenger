# Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在上线前补齐配置误填检测、LLM 截断识别、runtime 部分失败语义和部署锁文件。

**Architecture:** 只做最小硬化，不改交易主流程边界。配置层增加 `.env` 未知键校验；LLM 层增强 OpenAI 兼容接口请求与响应校验；runtime 层把“成功完成”拆成真实执行统计；部署层补一份当前已验证的约束锁文件。

**Tech Stack:** Python, pytest, pydantic-settings, requests, CLI runtime

---

### Task 1: Unknown Env Key Validation

**Files:**
- Modify: `config/settings.py`
- Modify: `cli_app/config_workflows.py`
- Test: `tests/test_settings_validation.py`
- Test: `tests/test_cli_config_workflows.py`

- [ ] 写 failing test，覆盖 `.env` 中出现未知键时会被识别
- [ ] 运行单测确认当前失败
- [ ] 实现 `.env` 未知键扫描与报错/提示
- [ ] 回跑单测确认通过

### Task 2: LLM Structured Response Guard

**Files:**
- Modify: `core/analysis/llm_brain.py`
- Test: `tests/test_llm_brain.py`

- [ ] 写 failing test，覆盖 `finish_reason=length` 时拒绝结果
- [ ] 写 failing test，覆盖请求带 JSON 输出约束
- [ ] 运行单测确认当前失败
- [ ] 实现 finish_reason 检查与结构化输出请求
- [ ] 回跑单测确认通过

### Task 3: Runtime Partial Failure Semantics

**Files:**
- Modify: `cli_app/runtime_execution.py`
- Test: `tests/test_cli_runtime_cycle.py`

- [ ] 写 failing test，覆盖“部分失败但仍返回 0”的现状
- [ ] 运行单测确认当前失败
- [ ] 实现 partial failure 统计与日志修正
- [ ] 回跑单测确认通过

### Task 4: Deployment Constraints

**Files:**
- Create: `constraints.txt`
- Modify: `README.md`
- Test: `tests/test_requirements_manifest.py`

- [ ] 生成当前直接/传递依赖约束文件
- [ ] 在 README 加入安装建议
- [ ] 写或补最小测试约束文件存在性/清单关系
- [ ] 回跑相关测试

### Task 5: Verification

**Files:**
- None

- [ ] 运行 targeted pytest
- [ ] 运行 full pytest
- [ ] 运行 `./okx config-check`
- [ ] 提交并推送
