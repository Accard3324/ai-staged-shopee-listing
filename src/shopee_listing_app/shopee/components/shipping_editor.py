SHIPPING_STATUS_SCRIPT = """
(() => {
  const panel = document.querySelector(".product-shipping");
  const text = panel ? panel.innerText : document.body.innerText || "";
  return {
    hasPanel: !!panel || /物流|运费|Shipping|Doorstep/.test(text),
    hasRates: /RM\\s?\\d|SHOPEE物流服务|Doorstep|Economy/.test(text)
  };
})()
"""
