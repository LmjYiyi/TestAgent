# 接口基本信息  =======全局参数  
**应用**:信用卡服务
**接口名**:CreditCardService.transferPay
**接口中文名**:信用卡转账支付
**URL**:http://localhost:8080/api/creditcard/transferPay/V1
**版本号**:V1

---

# 通用请求头
|参数名	|类型 |是否必输|最大长度|描述|示例值|
|-------|-------|-------|-----|-------|-------|
|X-Request-App|string|是|10|请求应用名|F-CCPS|
|X-Request-Id|string|是|10|请求应用号|2010434|

---

# 通用请求参数  
**类型**:通用请求参数

|参数名	 |类型	 |是否必输 |最大长度 | 描述   |示例值 |
|-------|-------|-------|-------|-------|-------|
|chk_name_flag|string|是|1|姓名检查标志，0-不检查，1-检查|1|
|person_name|string|否|60|用户姓名，当姓名检查标志为1时需上送|张三|
|transfer_amount|bigdecimal|是|10|转账金额|1.00|
|fee_type|string|否|1|手续费类型，0-无手续费，1-收取异地手续费|0|
|transfer_currency_type|string|是|1|转账币种类型，0-人民币，1-外币|0|
|transfer_currency|int|是|3|转账币种，156-CNY,840-USD|156|
|chk_local_flag|string|否|1|是否支持异地卡处理标志，0-不支持，1-支持|1|
|over_flag|string|否|1|透支标志，0-不透支，1-透支|1|
|counterParams|object|是|-|对方账户信息参数|-|
| ├─ counter_account|string|是|20|对方账号|1234567890|
| ├─ field1 | string |否| 信息1 |--|
| ├─ field2 | string |否| 信息2 |--|
|cardChkParams|object|是|-|卡检查参数|-|
| ├─ card_no|string|是|19|卡号|6226220000000000|
| ├─ card_pin_chk_flag|string|否|1|卡密码检查标志，0-不检查，1-检查|1|
| ├─ card_pin|string|否|6|卡密码|123456|
| ├─ card_expired_flag|string|否|1|卡有效期检查标志，0-不检查，1-检查|1|
| ├─ card_expired_date|string|否|6|卡片有效期|202701|
|InfoParams|object|是|-|交易信息参数|-|
| ├─ trx_zoneno|int|是|5|交易地区|200|
| ├─ trx_workdate|Date|是|10|交易日期|yyyy-MM-dd|
| ├─ trx_time|Time|是|8|交易时间|HH:mm:ss|
|cerChkParams|object|否|-|身份检查参数|-|
| ├─ cer_chk|string|否|1|证件检查标志，0-不检查，1-检查|1|
| ├─ cer_type|string|否|3|证件类型，0-身份证，1-护照，3-港澳台通行证|0|
| └─ cer_no|string|否|20|证件号码|441323200001010098|

---

# 通用响应参数  
**类型**:通用响应参数

|参数名	|类型 |是否必输|最大长度|描述|示例值|
|-------|-------|-------|-------|-------|-------|
|return_code|string|是|10|交易返回码，成功返回0，失败返回错误码|ERR1003|
|return_msg|string|是|200|错误码说明，交易成功是为空，交易失败时为错误码说明|校验身份信息失败|
|trx_serno|string|是|20|交易序号|233344455|
|card_no|string|是|19|卡号|6226220000000000|
|usable_amount|bigdecimal|是|10|余额|100.00|
|over_amount|bigdecimal|是|10|透支金额|0.00|
|data | object |否|返回对象 |--|
| ├─ field1 | string |是| 信息1 |--|
| ├─ field2 | object |否| 信息2 |--|
| │  ├─ sub_field1 | int |是| 子信息1 |--|
| │  └─ sub_field2 | bool |否| 子信息2 |--|
| └─ field3 | string |是| 信息3 |--|

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支1-基准分支-正常交易
**关键词**:信用卡, 转账, 正常交易

场景描述：
信用卡转账支付-基准分支。若无特殊测试场景，则使用该分支，默认覆盖内容：本地人民币交易，支持透支，无手续费。

**relevant_tables**:
credit_card_account

**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_base_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "John Zhang",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000001"
        },
        "cardChkParams": {
            "card_no": "6226220000000000",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000000",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。确定交易地区`trx_zoneno`为200，转账金额`transfer_amount`为1.00。在`credit_card_account`表查找开卡地区为200，且`usable_amount`（可用余额）大于`transfer_amount`的信用卡，获取其`card_no`（卡号），`person_name`（户名）和`usable_amount`（可用余额）作为测试数据。
2. 步骤二：构造请求报文。将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支2-异地交易
**关键词**:信用卡, 转账, 异地交易

场景描述：
信用卡转账支付-异地交易。测试异地交易场景，验证手续费计算和交易流水记录。

**relevant_tables**:
credit_card_account

**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_remote_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "Mike Li",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000000"
        },
        "cardChkParams": {
            "card_no": "6226220000000001",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000001",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张开卡地区不为200，且`usable_amount`（可用余额）大于`transfer_amount`=1.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。
2. 步骤二：构造请求报文。确定交易地区`trx_zoneno`为200，`chk_local_flag`（是否支持异地卡处理标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支3-外币交易
**关键词**:信用卡, 转账, 外币交易

场景描述：
信用卡转账支付-外币交易。测试外币交易场景，验证汇率换算和外币交易手续费。

**relevant_tables**:
credit_card_account

**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_foreign_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "Sun Ba",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "1",
        "transfer_currency": 840,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000000"
        },
        "cardChkParams": {
            "card_no": "6226220000000005",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000005",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张`usable_amount`（可用余额）大于`transfer_amount`=1.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。
2. 步骤二：构造请求报文。确定外币币种`transfer_currency`为840(USD)，`transfer_currency_type`（转账币种类型）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`+手续费（`transfer_amount`的1.5%）。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支4-收取手续费分支
**关键词**:信用卡, 转账, 手续费

场景描述：
信用卡转账支付-收取手续费分支。测试收取手续费场景，验证异地大额转账手续费计算。

**relevant_tables**:
credit_card_account


**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_fee_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "Mike Li",
        "transfer_amount": 10.00,
        "fee_type": "1",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000000"
        },
        "cardChkParams": {
            "card_no": "6226220000000001",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000001",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张开卡地区不为200，`usable_amount`（可用余额）大于`transfer_amount`=10.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。
2. 步骤二：构造请求报文。确定手续费类型`fee_type`为1(异地手续费)，交易地区`trx_zoneno`为200，转账金额`transfer_amount`为10.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`+手续费（手续费为5元和转账金额的1%两者的最大值） 也就是可用金额前后差值=转账金额+手续费。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支5-不透支场景分支
**关键词**:信用卡, 转账, 不透支

场景描述：
信用卡转账支付-不透支场景分支。测试不透支场景，验证余额不足时的错误处理。

**relevant_tables**:
credit_card_account


**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_no_overdraft_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "Zhao Liu",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "0",
        "counterParams": {
            "counter_account": "6226220000000000"
        },
        "cardChkParams": {
            "card_no": "6226220000000003",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 400,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "ERR1001",
    "return_msg": "余额不足",
    "trx_serno": "...",
    "card_no": "6226220000000003",
    "usable_amount": "...",
    "over_amount": "...",
    "data": null
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张`usable_amount`（可用余额）不足以完成`transfer_amount` = 10.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。
2. 步骤二：构造请求报文。设置`over_flag`（透支标志）为0(不透支)，转账金额`transfer_amount`为10.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'ERR1001'，`return_msg`为'余额不足'，表示交易失败。同时，查询`credit_card_account`表，验证`usable_amount`未发生变化，确认交易未执行。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支6-卡检查分支
**关键词**:信用卡, 转账, 卡检查

场景描述：
信用卡转账支付-卡检查分支。测试卡检查场景，验证卡号、密码和有效期。

**relevant_tables**:
credit_card_account


**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_card_check_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "John Zhang",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000001"
        },
        "cardChkParams": {
            "card_no": "6226220000000000",
            "card_pin_chk_flag": "1",
            "card_pin": "123456",
            "card_expired_flag": "1",
            "card_expired_date": "202701"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "0"
        }
    }
}
```

**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000000",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张状态正常的信用卡，获取其`card_no`（卡号）、`card_pin`（密码）和`card_expired_date`（过期时间），`card_no`（卡号），`usable_amount`（可用余额）和`person_name`（户名），作为测试数据。
2. 步骤二：构造请求报文。设置`card_pin_chk_flag`（卡密码检查标志）为1，`card_expired_flag`（卡片有效期检查标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。

---

# 接口场景  
**类型**:接口场景
**场景名**:信用卡转账支付-场景分支7-客户身份检查分支
**关键词**:信用卡, 转账, 身份检查

场景描述：
信用卡转账支付-客户身份检查分支。测试客户身份检查场景，验证用户身份信息。

**relevant_tables**:
credit_card_account

**request_payload**:
```json
{
    "url": "http://localhost:8080/api/creditcard/transferPay/V1",
    "method": "POST",
    "headers": {
        "Content-Type": "application/json",
        "X-Request-App": "ICBC_TestAgent",
        "X-Request-Id": "req_identity_check_001"
    },
    "json_body": {
        "chk_name_flag": "1",
        "person_name": "John Zhang",
        "transfer_amount": 1.00,
        "fee_type": "0",
        "transfer_currency_type": "0",
        "transfer_currency": 156,
        "chk_local_flag": "1",
        "over_flag": "1",
        "counterParams": {
            "counter_account": "6226220000000001"
        },
        "cardChkParams": {
            "card_no": "6226220000000000",
            "card_pin_chk_flag": "0"
        },
        "infoParams": {
            "trx_zoneno": 200,
            "trx_workdate": "2025-07-26",
            "trx_time": "15:30:00"
        },
        "cerChkParams": {
            "cer_chk": "1",
            "cer_type": "0",
            "cer_no": "441323200001010098"
        }
    }
}
```


**expected_response**:
```json
{
    "return_code": "0",
    "return_msg": "",
    "trx_serno": "...",
    "card_no": "6226220000000000",
    "usable_amount": "...",
    "over_amount": "...",
    "data": {
        "field1": "...",
        "field2": {
            "sub_field1": "...",
            "sub_field2": "..."
        },
        "field3": "..."
    }
}
```

步骤：
1. 步骤一：准备测试数据。在`credit_card_account`表中，查找一张状态正常的卡，获取其`card_no`（卡号）获取用户`person_name`（姓名）、`cer_type`（证件类型）和`cer_no`（证件号码），`usable_amount`（可用余额）。作为测试数据。
2. 步骤二：构造请求报文。设置`cer_chk`（证件检查标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板`request_payload`当中，生成最终的API请求。
3. 步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。
4. 步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。
