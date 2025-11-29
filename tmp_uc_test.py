import time, traceback
import undetected_chromedriver as uc
opts=uc.ChromeOptions()
opts.add_argument('--disable-blink-features=AutomationControlled')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')

def main():
    try:
        driver=uc.Chrome(options=opts, use_subprocess=False)
        driver.get('https://www.xiaohongshu.com')
        time.sleep(5)
        print('title', driver.title)
        driver.quit()
    except Exception:
        traceback.print_exc()

if __name__=='__main__':
    main()
