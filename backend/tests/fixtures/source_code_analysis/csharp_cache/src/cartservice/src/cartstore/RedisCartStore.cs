using Microsoft.Extensions.Caching.Distributed;

public class RedisCartStore : ICartStore
{
    private readonly IDistributedCache _cache;

    public RedisCartStore(IDistributedCache cache)
    {
        _cache = cache;
    }

    public async Task<string> GetCart(string userId)
    {
        return await _cache.GetAsync(userId);
    }

    public async Task SetCart(string userId, string value)
    {
        await _cache.SetAsync(userId, value);
    }
}
