const cookie = `colorscheme=light; session=cefc6cd1cfb39aa237b77b63be917b9c; smac=1773051427-cUdqjBBH5qCKrM7CUpAmVXXxngEgMhu1yLBz4Oqpu4o; hmti_=1774501715-hXzoPiEuBiAff1Wav8RZJ2SYsw-3ruNY13bpC7lDC9Yg; fog=1d8f27fab484d70e50feaad18b108573a024f2ae3be32a8d91215314941f5b20; cf_clearance=pxiVLpDEybwSp19UnVJMib75_xZKBZQDeBFDko20pSI-1774543383-1.2.1.1-yEGbHkanfVoYAePhHX2Kqb4QuKsQbLglzJHZ8EVJ42ZgYIJO4Q96F4dp5McYVajHvuOXA0ZF3oY2P8Id5yE85vVgCzw1sKyKKty78KZZmrB1NrWklFf9Zpp_GYhaJ6kQBBpITlKITBYPH6C7_KLnPE9Iw2a41_tPsEIQc8pC2Cq3v6KhYhOHYj9eJfRl0PT9WPVdWFo_NxoyA7TbxnXDCLPP62p9yf5MH7HFdUni_aw`;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

async function test(threadId) {
    const headers = {
      'User-Agent': UA,
      Cookie: cookie,
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    };
    
    // 1. Get CF token / post-id
    const pageRes = await fetch(`https://www.nodeseek.com/post-${threadId}-1`, {
        headers: headers,
        redirect: 'follow'
    });
    const pageHtml = await pageRes.text();
    console.log("Page Fetch Status:", pageRes.status);
    if (!pageRes.ok) {
        console.log("Failed to fetch page. HTML snippet:", pageHtml.substring(0, 500));
        return;
    }
    
    const csrfMatch = pageHtml.match(/<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"/i) || 
                      pageHtml.match(/csrfToken["']?\s*[:=]\s*["']([^"']+)["']/);
    const csrfToken = csrfMatch ? csrfMatch[1] : (cookie.match(/(?:csrf|token)=([^;]+)/i)?.[1] || null);
    
    // Some threads have <div ... data-post-id="1234"> or <article data-post-id="1234">
    // Looking at actual nodeseek html, it might not be data-post-id. Let's find out:
    const postIdMatch = pageHtml.match(/data-post-id="(\d+)"/);
    console.log("CSRF:", csrfToken);
    console.log("Post ID extracted via regex:", postIdMatch ? postIdMatch[1] : 'NOT FOUND');
    
    if (!postIdMatch) {
       console.log("Could not find data-post-id. Let's dump a snippet of the page HTML:");
       const match2 = pageHtml.match(/post-id/i);
       if(match2) {
           const pos = pageHtml.indexOf("post-id", match2.index - 50);
           console.log("Found post-id near:", pageHtml.substring(pos, pos + 200));
       }
       // Notice that sometimes nodeseek API only needs threadId, but looking at nodeseek.ts it passes `post_id: parseInt(postIdMatch[1])`. Wait, what IS post_id anyway?
       // Usually thread ID IS the post_id ? In NodeSeek `/post-123456-1`, 123456 IS the post_id conceptually.
       console.log("Will fallback to post_id = threadId");
    }
    
    let pid = postIdMatch ? parseInt(postIdMatch[1]) : parseInt(threadId);

    const apiHeaders = {
        ...headers,
        'Content-Type': 'application/json',
        Origin: 'https://www.nodeseek.com',
        Referer: `https://www.nodeseek.com/post-${threadId}-1`
    };
    if (csrfToken) apiHeaders['Csrf-Token'] = csrfToken;
    
    const body = { content: "支持一下，好用", post_id: pid };
    
    console.log("POST /api/content/new-comment ... with payload:", body);
    const res = await fetch('https://www.nodeseek.com/api/content/new-comment', {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify(body)
    });
    
    console.log("POST Status:", res.status);
    const text = await res.text();
    console.log("POST Response:", text);
}

test('666691').catch(console.error);
