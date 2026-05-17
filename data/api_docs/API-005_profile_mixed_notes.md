# 用户资料接口

接口列表：

## 获取资料

GET `/user/profile`

返回字段：avatar、nickname、gender、birthday、bio、updated_at

## 更新资料

PUT `/user/profile`

body:

```text
avatar: string?
nickname: string required
gender: string?
birthday: yyyy-MM-dd?
bio: string?
```

错误码：

- 6001 昵称为空
- 6002 昵称太长
- 6003 命中敏感词
- 6004 生日非法
- 6005 头像格式不支持
- 6006 头像过大

问题：

- avatar 上传是单独接口还是 base64 直接传？目前前后端说法不一致。
- bio 超长时是截断还是报错？待定。

