# 自动化失败修复技能

## 目标

当用户要诊断并修复自动化脚本失败时，使用这个技能。

目标是判断失败来自脚本逻辑、selector 变化、时序、测试数据、环境，还是产品本身缺陷。

## 触发条件

当主意图是 `AUTOMATION_FAILURE_FIX` 时使用。

典型请求：

```text
Playwright 脚本断言失败，帮我修一下
自动化 case 失败了
selector 定位不到
等待超时
Selenium 找不到元素
```

## 输入

```text
失败日志
失败脚本路径
自动化框架
截图 / trace / 网络日志
失败用例名称
最近页面、接口或数据变更
```

## 工作流程

1. 先读失败信号。

   识别失败类型：

   ```text
   selector 定位问题
   断言失败
   等待超时
   测试数据问题
   框架配置问题
   产品功能问题
   ```

2. 查看失败脚本和相关 helper 封装。

3. 对比预期行为和实际失败证据。

4. 判断应该修脚本，还是转到产品失败排查。

5. 做最小且安全的修改。

6. 运行失败用例，或给出验证命令。

7. 说明根因、修改文件和验证结果。

## 计划接入的工具

```text
search_code(query)
read_file(path)
write_file(path)
run_test(command)
analyze_trace(file)
analyze_console_log(file)
```

## 输出约定

```json
{
  "failure_type": "...",
  "root_cause": "...",
  "changed_files": [],
  "verification_command": "...",
  "verification_result": "...",
  "remaining_risk": []
}
```

## 质量检查

```text
是否误把产品问题修成脚本兼容
是否无依据修改断言
是否只扩大 timeout
是否保留关键覆盖
是否运行最小验证
```

## 禁止事项

```text
不要删除失败步骤
不要删除断言来让测试通过
不要盲目扩大 timeout
不要隐藏真实产品缺陷
```

## 兜底策略

如果缺少日志或脚本路径：

```text
要求用户补充失败日志和脚本路径
不要猜测式修改代码
```

如果看起来是产品行为异常：

```text
转到 FAILURE_TRIAGE 或 BUG_REPORT_GENERATION
```
