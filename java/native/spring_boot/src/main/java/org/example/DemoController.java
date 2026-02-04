package org.example;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DemoController {

    @Autowired
    private ChatService chatService;

    /**
     * 统一调用接口
     * 同时演示：手动 Trace 上报 (LLM 模拟) + Prompt 执行
     * Main运行起来后，使用示例curl调用即可，或根据实际情况修改：curl "http://localhost:8080/chat?query=hello&key=CozeLoop_Oncall_Master"
     */
    @GetMapping("/chat")
    public String chat(
            @RequestParam(required = false) String key,
            @RequestParam(defaultValue = "Hello") String query) {
        return chatService.chat(key, query);
    }
}
