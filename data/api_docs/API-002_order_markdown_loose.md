# 订单接口草稿

接口：POST /order/create

说明：创建订单，前端确认订单页点击提交时调用。

参数大概如下：

- skuId: 商品 SKU
- count: 数量
- addressId: 地址
- couponId: 优惠券，可为空
- source: app/h5

返回：

成功：

```json
{
  "code": 0,
  "data": {
    "orderNo": "O202604010001",
    "payExpireAt": "2026-04-01 12:15:00"
  }
}
```

失败：

库存不足 code=3001
商品下架 code=3002
地址无效 code=3003
优惠券不可用 code=3004

备注：是否需要传 userId？后端说从 token 里取，但文档没最终确认。

