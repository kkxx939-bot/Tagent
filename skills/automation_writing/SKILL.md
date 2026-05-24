# 自动化编写技能

## 目标

当用户要基于测试用例、需求或接口场景生成或更新自动化测试代码时，使用这个技能。

生成代码应贴合现有项目框架，不要另起一套自动化风格。

## 触发条件

当主意图是 `AUTOMATION_WRITING` 时使用。

典型请求：

```text
把这条用例生成 Playwright 自动化脚本
帮我写 Selenium 自动化
根据登录测试用例生成 pytest 自动化
把接口测试场景转成自动化代码
```

如果用户是要修失败的自动化脚本，不使用这个技能，应转到 `AUTOMATION_FAILURE_FIX`。

## 输入

```text
目标用例或需求
自动化框架
目标项目路径
已有 helper / fixture / Page Object
测试数据准备方式
运行命令
```

## 工作流程

1. 明确目标测试。

   判断来源属于：

   ```text
   已有用例
   生成用例
   需求说明
   API 场景
   Bug 回归
   ```

2. 查看项目现有自动化框架。

   写新代码前，先读已有测试代码。

3. 复用本地项目习惯。

   优先复用已有的：

   ```text
   helper
   fixture
   Page Object
   selector 约定
   测试数据工厂
   断言风格
   ```

4. 生成最小且有用的代码改动。

5. 运行验证，或给出验证命令。

6. 说明修改文件和验证结果。

## 计划接入的工具

```text
search_code(query)
read_file(path)
write_file(path)
run_test(command)
```

## 输出约定

```json
{
  "target_case": "...",
  "created_or_modified_files": [],
  "test_command": "...",
  "verification_result": "...",
  "notes": []
}
```

## 质量检查

```text
是否复用已有框架
是否复用已有 helper
是否避免 固定 sleep
selector 是否稳定
断言是否清晰
测试数据是否隔离
是否可独立运行
```

## 禁止事项

```text
不要引入新框架替代现有框架
不要用固定 sleep 掩盖等待问题
不要删除断言
不要写无法运行的伪代码
```

## 兜底策略

如果无法识别自动化框架：

```text
要求用户补充框架或项目路径
先返回计划，不直接写代码
```

如果测试无法运行：

```text
说明应该运行的命令
明确说明尚未执行验证
```
