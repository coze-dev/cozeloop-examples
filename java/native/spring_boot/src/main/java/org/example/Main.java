package org.example;

import com.coze.loop.spring.autoconfigure.CozeLoopAutoConfiguration;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Import;

/**
 * CozeLoop Spring Boot 使用示例
 *
 * <p>本示例展示了如何利用 cozeloop-spring-boot-starter 简化集成过程。
 * 
 * <p>注意：当前版本的 Starter (0.1.0) 可能未在 META-INF 中注册自动配置，
 * 因此我们在这里通过 @Import 手动导入 CozeLoopAutoConfiguration。
 */
@SpringBootApplication
@Import(CozeLoopAutoConfiguration.class)
public class Main {
    public static void main(String[] args) {
        SpringApplication.run(Main.class, args);
    }
}
