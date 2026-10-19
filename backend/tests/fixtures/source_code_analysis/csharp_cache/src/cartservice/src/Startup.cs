using Microsoft.Extensions.Caching.StackExchangeRedis;

public class Startup
{
    public void ConfigureServices(IServiceCollection services)
    {
        services.AddStackExchangeRedisCache(options =>
        {
            options.Configuration = "redis-cart:6379";
        });
    }
}
