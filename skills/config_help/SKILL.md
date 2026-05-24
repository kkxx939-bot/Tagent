# 配置帮助技能

## 目标

当用户询问模型、API Key、环境变量、base URL 或本地配置问题时，使用这个技能。

## 触发条件

当主意图是 `CONFIG_HELP` 时使用。

典型请求：

```text
LLM_API_KEY 怎么配置
DeepSeek base_url 是哪里
模型调用失败怎么处理
config.py 这个配置什么意思
```

## 输入

```text
配置问题
错误日志
相关配置文件
运行命令
```

## 工作流程

1. 定位配置来源。

2. 检查配置优先级。

   当前项目模式：

   ```text
   环境变量
   config.py 默认值
   ```

3. 识别缺失或不安全的配置。

4. 给出安全的修复建议。

5. 避免暴露密钥。

## 当前项目组件

```text
config.py
config.example
llm_client.py
```

## 输出约定

```json
{
  "problem": "...",
  "config_source": "...",
  "fix_suggestion": "...",
  "security_notes": []
}
```

## 质量检查

```text
是否说明配置来源
是否说明环境变量优先级
是否避免泄露 API Key
是否给出可执行修复建议
```

## 禁止事项

```text
不要输出完整 API Key
不要建议把密钥提交到 git
不要把敏感配置写入示例输出
```

## 兜底策略

如果配置来源不明确：

```text
先搜索配置和环境变量引用
要求用户补充准确的错误信息
```
