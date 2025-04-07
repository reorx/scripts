from BingImageCreator import ImageGen
import sys
import os
import datetime


def main():
    prompt = sys.argv[1]
    out_dir = 'images'
    bing_create_image(prompt, out_dir)


def bing_create_image(prompt, out_dir):
    i = ImageGen(get_bing_cookie())
    images = i.get_images(prompt)
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    date_path = os.path.join(out_dir, date_str)
    if not os.path.exists(date_path):
        os.mkdir(date_path)
    i.save_images(images, date_path)
    print(images)


def get_bing_cookie():
    with open('.bing_cookie.txt', 'r') as f:
        return f.read().strip()


if __name__ == '__main__':
    main()
