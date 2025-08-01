# API接口信息配置
API_INFO = {
    "UniformTeller.qryTellerInfo": {
        "name": "UniformTeller.qryTellerInfo",
        "chinese_name": "统一认证用户信息查询",
        "url": "http://localhost:8080/api/aam/uniformteller/qrytellerInfo/V1",
        "method": "POST",
        "headers": {
            "X-Request-App": "F-CCPS",
            "X-Request-Id": "2010434"
        }
    },
    "CreditCardService.transferPay": {
        "name": "CreditCardService.transferPay",
        "chinese_name": "信用卡转账支付",
        "url": "http://localhost:8080/api/creditcard/transferPay/V1",
        "method": "POST",
        "headers": {
            "X-Request-App": "ICBC_TestAgent",
            "X-Request-Id": "req_base_001"
        }
    }
}

# 测试场景配置
TEST_SCENARIOS = {
    # UniformTeller.qryTellerInfo scenarios
    "统一认证用户信息查询 - 场景分支1：验证统一认证号分支": {
        "description": "测试 `ssicType` 为 \"1\" (统一认证号) 的认证结果。",
        "relevant_tables": ["teller_info"],
        "request_payload": {
            "url": "http://localhost:8080/api/aam/uniformteller/qrytellerInfo/V1",
            "method": "POST",
            "headers": {
                "X-Request-App": "F-CCPS",
                "X-Request-Id": "2010434"
            },
            "json_body": {
                "ssicType": "1",
                "ssicId": "123456789",
                "username": "xx",
                "email": "zhangsan@example.com",
                "phone": "13800138001",
                "biz_content": {
                    "serviceName": "AAM",
                    "randomKey": "smxxxxxxxxsm4",
                    "timestamp": "2019-07-01 09:01:01"
                }
            }
        },
        "expected_response": {
            "return_code": "0",
            "data": {
                "field1": "统一认证用户-123456789"
            }
        },
        "steps": [
            "步骤一：准备测试数据。根据测试场景，查询并准备`ssicType`为 '1' 的用户数据作为前置条件。",
            "步骤二：构造请求报文。将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向 `UniformTeller.qryTellerInfo` 接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为 200，同时断言响应体内容,确保 `return_code` 为 '0' 且 响应体 `data` 中的 `field1` 字段值符合预期，其值应包含前缀 '统一认证用户-'",
        ]
    },
    "统一认证用户信息查询 - 场景分支2：验证身份证信息分支": {
        "description": "测试 `ssicType` 为 \"2\" (身份证) 的认证结果。",
        "relevant_tables": ["teller_info"],
        "request_payload": {
            "url": "http://localhost:8080/api/aam/uniformteller/qrytellerInfo/V1",
            "method": "POST",
            "headers": {
                "X-Request-App": "F-CCPS",
                "X-Request-Id": "2010434"
            },
            "json_body": {
                "ssicType": "2",
                "ssicId": "110101199001011234",
                "username": "xx",
                "email": "wangwu@example.com",
                "phone": "13800138003",
                "biz_content": {
                    "serviceName": "AAM",
                    "randomKey": "smxxxxxxxxsm4",
                    "timestamp": "2019-07-01 09:01:01"
                }
            }
        },
        "expected_response": {
            "return_code": "0",
            "data": {
                "field1": "身份证用户-110101199001011234"
            }
        },
        "steps": [
            "步骤一：准备测试数据。根据测试场景，查询并准备`ssicType`为 '2' 的用户数据作为前置条件。",
            "步骤二：构造请求报文。将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向 `UniformTeller.qryTellerInfo` 接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为 200，同时断言响应体内容,确保 `return_code` 为 '0' 且 响应体 `data` 中的 `field1` 字段值符合预期，其值应包含前缀 '身份证用户-'",
        ]
    },
    "统一认证用户信息查询 - 场景分支3：验证香港身份证分支": {
        "description": "测试 `ssicType` 为 \"3\" (香港身份证) 的认证结果。",
        "relevant_tables": ["teller_info"],
        "request_payload": {
            "url": "http://localhost:8080/api/aam/uniformteller/qrytellerInfo/V1",
            "method": "POST",
            "headers": {
                "X-Request-App": "F-CCPS",
                "X-Request-Id": "2010434"
            },
            "json_body": {
                "ssicType": "3",
                "ssicId": "B234567(8)",
                "username": "xxx",
                "email": "xx@example.com",
                "phone": "+8613812345678",
                "biz_content": {
                    "serviceName": "AAM",
                    "randomKey": "smxxxxxxxxsm4",
                    "timestamp": "2025-07-15 11:03:46"
                }
            }
        },
        "expected_response": {
            "return_code": "0",
            "data": {
                "field1": "香港身份证用户-B234567(8)"
            }
        },
        "steps": [
            "步骤一：准备测试数据。根据测试场景，查询并准备`ssicType`为 '3' 的用户数据作为前置条件。",
            "步骤二：构造请求报文。将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向 `UniformTeller.qryTellerInfo` 接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为 200，同时断言响应体内容,确保 `return_code` 为 '0' 且 响应体 `data` 中的 `field1` 字段值符合预期，其值应包含前缀 '香港身份证用户-'",
        ]
    },
    
    # CreditCardService.transferPay scenarios
    "信用卡转账支付-场景分支1-基准分支-正常交易": {
        "description": "信用卡转账支付-基准分支。若无特殊测试场景，则使用该分支，默认覆盖内容：本地人民币交易，支持透支，无手续费。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。确定交易地区`trx_zoneno`为200，转账金额`transfer_amount`为1.00。在`credit_card_account`表查找开卡地区为200，且`usable_amount`（可用余额）大于`transfer_amount`的信用卡，获取其`card_no`（卡号），`person_name`（户名）和`usable_amount`（可用余额）作为测试数据。",
            "步骤二：构造请求报文。将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。"
        ]
    },
    "信用卡转账支付-场景分支2-异地交易": {
        "description": "信用卡转账支付-异地交易。测试异地交易场景，验证手续费计算和交易流水记录。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张开卡地区不为200，且`usable_amount`（可用余额）大于`transfer_amount`=1.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。",
            "步骤二：构造请求报文。确定交易地区`trx_zoneno`为200，`chk_local_flag`（是否支持异地卡处理标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。"
        ]
    },
    "信用卡转账支付-场景分支3-外币交易": {
        "description": "信用卡转账支付-外币交易。测试外币交易场景，验证汇率换算和外币交易手续费。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张`usable_amount`（可用余额）大于`transfer_amount`=1.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。",
            "步骤二：构造请求报文。确定外币币种`transfer_currency`为840(USD)，`transfer_currency_type`（转账币种类型）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`+手续费（`transfer_amount`的1.5%）。"
        ]
    },
    "信用卡转账支付-场景分支4-收取手续费分支": {
        "description": "信用卡转账支付-收取手续费分支。测试收取手续费场景，验证异地大额转账手续费计算。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张开卡地区不为200，`usable_amount`（可用余额）大于`transfer_amount`=10.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。",
            "步骤二：构造请求报文。确定手续费类型`fee_type`为1(异地手续费)，交易地区`trx_zoneno`为200，转账金额`transfer_amount`为10.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`+手续费（手续费为5元和转账金额的1%两者的最大值） 也就是可用金额前后差值=转账金额+手续费。"
        ]
    },
    "信用卡转账支付-场景分支5-不透支场景分支": {
        "description": "信用卡转账支付-不透支场景分支。测试不透支场景，验证余额不足时的错误处理。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
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
        },
        "expected_response": {
            "return_code": "ERR1001",
            "return_msg": "余额不足",
            "trx_serno": "...",
            "card_no": "6226220000000003",
            "usable_amount": "...",
            "over_amount": "...",
            "data": None
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张`usable_amount`（可用余额）不足以完成`transfer_amount` = 10.00的信用卡，获取其`card_no`（卡号）和`person_name`（户名），`usable_amount`（可用余额）作为测试数据。",
            "步骤二：构造请求报文。设置`over_flag`（透支标志）为0(不透支)，转账金额`transfer_amount`为10.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'ERR1001'，`return_msg`为'余额不足'，表示交易失败。同时，查询`credit_card_account`表，验证`usable_amount`未发生变化，确认交易未执行。"
        ]
    },
    "信用卡转账支付-场景分支6-卡检查分支": {
        "description": "信用卡转账支付-卡检查分支。测试卡检查场景，验证卡号、密码和有效期。",
        "relevant_tables": ["credit_card_account"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
            "headers": {
                "Content-Type": "application/json",
                "X-Request-App": "ICBC_TestAgent",
                "X-Request-Id": "req_card_check_001"
            },
            "body": {
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张状态正常的信用卡，获取其`card_no`（卡号）、`card_pin`（密码）和`card_expired_date`（过期时间），`card_no`（卡号），`usable_amount`（可用余额）和`person_name`（户名），作为测试数据。",
            "步骤二：构造请求报文。设置`card_pin_chk_flag`（卡密码检查标志）为1，`card_expired_flag`（卡片有效期检查标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。"
        ]
    },
    "信用卡转账支付-场景分支7-客户身份检查分支": {
        "description": "信用卡转账支付-客户身份检查分支。测试客户身份检查场景，验证用户身份信息。",
        "relevant_tables": ["credit_card_account", "user_info"],
        "request_payload": {
            "method": "POST",
            "url": "http://localhost:8080/api/creditcard/transferPay/V1",
            "headers": {
                "Content-Type": "application/json",
                "X-Request-App": "ICBC_TestAgent",
                "X-Request-Id": "req_identity_check_001"
            },
            "body": {
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
        },
        "expected_response": {
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
        },
        "steps": [
            "步骤一：准备测试数据。在`credit_card_account`表中，查找一张状态正常的卡，获取其`card_no`（卡号）获取用户`person_name`（姓名）、`cer_type`（证件类型）和`cer_no`（证件号码），`usable_amount`（可用余额）。作为测试数据。",
            "步骤二：构造请求报文。设置`cer_chk`（证件检查标志）为1，转账金额`transfer_amount`为1.00。并且将步骤一中准备的数据填充至请求报文模板'request_payload'当中，生成最终的API请求。",
            "步骤三：执行API调用。使用构造好的请求报文，向`CreditCardService.transferPay`接口发送POST请求。",
            "步骤四：校验与断言。验证API响应的HTTP状态码为200，`return_code`为'0'，表示交易成功。同时，查询`credit_card_account`表，对比交易前后`usable_amount`的差值是否等于`transfer_amount`。"
        ]
    }
}

# 获取所有场景名称
def get_all_scenarios():
    """获取所有测试场景名称列表"""
    return list(TEST_SCENARIOS.keys())

# 根据场景名称获取场景数据
def get_scenario_by_name(scenario_name):
    """根据场景名称获取场景详细数据"""
    return TEST_SCENARIOS.get(scenario_name)

# 获取场景的相关表
def get_relevant_tables(scenario_name):
    """获取场景相关的数据库表"""
    scenario = TEST_SCENARIOS.get(scenario_name)
    if scenario:
        return scenario.get("relevant_tables", [])
    return []

# 获取场景的测试步骤
def get_scenario_steps(scenario_name):
    """获取场景的测试步骤"""
    scenario = TEST_SCENARIOS.get(scenario_name)
    if scenario:
        return scenario.get("steps", [])
    return []

# 根据API名称获取API信息
def get_api_info(api_name):
    """根据API名称获取API配置信息"""
    return API_INFO.get(api_name)

# 获取所有API名称
def get_all_apis():
    """获取所有API名称列表"""
    return list(API_INFO.keys())
